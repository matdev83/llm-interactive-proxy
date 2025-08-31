import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock
from src.connectors.gemini import GeminiBackend
from src.core.domain.chat import ChatMessage, ChatRequest

TEST_GEMINI_API_BASE_URL = "https://generativelanguage.googleapis.com"


@pytest_asyncio.fixture(name="gemini_backend")
async def gemini_backend_fixture():
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        yield GeminiBackend(
            client=client, config=config, translation_service=TranslationService()
        )


@pytest.fixture
def sample_chat_request_data() -> ChatRequest:
    return ChatRequest(
        model="test-model", messages=[ChatMessage(role="user", content="Hello")]
    )


@pytest.fixture
def sample_processed_messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="Hello")]


@pytest.mark.skip(reason="Streaming test needs to be rewritten")
@pytest.mark.asyncio
async def test_chat_completions_streaming_success(
    gemini_backend: GeminiBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: ChatRequest,
    sample_processed_messages: list[ChatMessage],
):
    # This test needs to be rewritten to properly handle the new response format
    pass
