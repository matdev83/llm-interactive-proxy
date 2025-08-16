
import httpx
import pytest
import pytest_asyncio
import src.models as models
from pytest_httpx import HTTPXMock
from src.connectors.openrouter import OpenRouterBackend
from starlette.responses import StreamingResponse

# Default OpenRouter settings for tests
TEST_OPENROUTER_API_BASE_URL = (
    "https://openrouter.ai/api/v1"  # Real one for realistic requests
)


def mock_get_openrouter_headers(key_name: str, api_key: str) -> dict[str, str]:
    # Create a mock config dictionary for testing
    mock_config = {
        "app_site_url": "http://localhost:test",
        "app_x_title": "TestProxy",
    }
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": mock_config["app_site_url"],
        "X-Title": mock_config["app_x_title"],
    }


@pytest_asyncio.fixture(name="openrouter_backend")
async def openrouter_backend_fixture():
    async with httpx.AsyncClient() as client:
        yield OpenRouterBackend(client=client)


@pytest.fixture(name="sample_chat_request_data")
def sample_chat_request_data_fixture():
    return models.ChatCompletionRequest(
        model="test-model",
        messages=[models.ChatMessage(role="user", content="Hello")],
    )


@pytest.fixture(name="sample_processed_messages")
def sample_processed_messages_fixture():
    return [models.ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
async def test_chat_completions_streaming_success(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: models.ChatCompletionRequest,
    sample_processed_messages: list[models.ChatMessage],
):
    sample_chat_request_data.stream = True
    effective_model = "openai/gpt-4"

    # Mock streaming response chunks
    stream_chunks = [
        b'data: {"id": "chatcmpl-xxxx", "object": "chat.completion.chunk", "created": 123, "model": "',
        bytes(effective_model, "utf-8"),
        b'", "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": null}]}\n\n',
        b'data: {"id": "chatcmpl-xxxx", "object": "chat.completion.chunk", "created": 123, "model": "',
        bytes(effective_model, "utf-8"),
        b'", "choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": null}]}\n\n',
        b'data: {"id": "chatcmpl-xxxx", "object": "chat.completion.chunk", "created": 123, "model": "',
        bytes(effective_model, "utf-8"),
        b'", "choices": [{"index": 0, "delta": {"content": " world!"}, "finish_reason": null}]}\n\n',
        b"data: [DONE]\n\n",
    ]

    httpx_mock.add_response(
        url=f"{TEST_OPENROUTER_API_BASE_URL}/chat/completions",
        method="POST",
        stream=httpx.ByteStream(b"".join(stream_chunks)),
        status_code=200,
        headers={"Content-Type": "text/event-stream"},
    )

    response = await openrouter_backend.chat_completions(
        request_data=sample_chat_request_data,
        processed_messages=sample_processed_messages,
        effective_model=effective_model,
        openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
        openrouter_headers_provider=mock_get_openrouter_headers,
        key_name="OPENROUTER_API_KEY_1",
        api_key="FAKE_KEY",
    )

    assert isinstance(response, StreamingResponse)

    # Collect all chunks from the streaming response
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)

    # Just verify we got chunks
    assert len(chunks) > 0