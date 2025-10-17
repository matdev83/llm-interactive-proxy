import httpx
import pytest
import pytest_asyncio
from src.connectors.openai_oauth import OpenAIOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest


@pytest_asyncio.fixture()
async def connector() -> OpenAIOAuthConnector:
    client = httpx.AsyncClient()
    config = AppConfig()
    instance = OpenAIOAuthConnector(client=client, config=config)
    try:
        yield instance
    finally:
        await client.aclose()


def test_is_codex_model_detection(connector: OpenAIOAuthConnector) -> None:
    assert connector._is_codex_model("gpt-5-codex") is True
    assert connector._is_codex_model("codex-mini-latest") is True
    assert connector._is_codex_model("gpt-4.1") is False


@pytest.mark.asyncio
async def test_build_codex_payload_structure(connector: OpenAIOAuthConnector) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hello Codex!")],
        model="gpt-5-codex",
        stream=True,
    )

    payload, conversation_id = connector._build_codex_payload(
        chat_request, chat_request.messages, "gpt-5-codex"
    )

    assert payload["model"] == "gpt-5-codex"
    assert payload["instructions"].startswith("You are Codex, based on GPT-5.")
    assert payload["stream"] is True
    assert payload["prompt_cache_key"] == conversation_id

    input_items = payload["input"]
    assert len(input_items) >= 3  # user instructions, environment context, user message
    assert input_items[0]["content"][0]["text"].startswith("<user_instructions>")
    assert input_items[1]["content"][0]["text"].startswith("<environment_context>")
    assert input_items[2]["content"][0]["text"] == "Hello Codex!"


@pytest.mark.asyncio
async def test_codex_headers_include_expected_fields() -> None:
    client = httpx.AsyncClient()
    config = AppConfig()
    connector = OpenAIOAuthConnector(client=client, config=config)
    headers = connector._build_codex_headers("conversation-id")
    assert headers["OpenAI-Beta"] == "responses=experimental"
    assert headers["conversation_id"] == "conversation-id"
    assert headers["session_id"] == "conversation-id"
    assert headers["Codex-Task-Type"] == "standard"
    assert headers["originator"] == connector.CODEx_ORIGINATOR
    assert "User-Agent" in headers
    await client.aclose()
