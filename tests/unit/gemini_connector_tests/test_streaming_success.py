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


@pytest.mark.asyncio
async def test_chat_completions_streaming_success(
    gemini_backend: GeminiBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: ChatRequest,
    sample_processed_messages: list[ChatMessage],
):
    # Arrange
    sample_chat_request_data = sample_chat_request_data.model_copy(
        update={"stream": True}
    )

    # Mock API endpoint
    url = f"{TEST_GEMINI_API_BASE_URL}/v1beta/models/test-model:streamGenerateContent"

    # Provide a minimal streaming-like response body (single JSON line)
    # pytest_httpx yields the full response content; GeminiBackend reads via aiter_text(),
    # which httpx.MockAPI also supports by chunking the text internally.
    httpx_mock.add_response(
        method="POST",
        url=url,
        status_code=200,
        json={"candidates": [{"content": {"parts": [{"text": "Hello stream"}]}}]},
        headers={"Content-Type": "application/json"},
    )

    # Act
    envelope = await gemini_backend.chat_completions(
        request_data=sample_chat_request_data,
        processed_messages=sample_processed_messages,
        effective_model="test-model",
        gemini_api_base_url=TEST_GEMINI_API_BASE_URL,
        api_key="FAKE_KEY",
    )

    # Assert
    from src.core.domain.responses import StreamingResponseEnvelope
    from src.core.interfaces.response_processor_interface import ProcessedResponse

    assert isinstance(envelope, StreamingResponseEnvelope)

    chunks = []
    async for chunk in envelope.content:  # type: ignore[union-attr]
        assert isinstance(chunk, ProcessedResponse)
        assert isinstance(chunk.content, str | bytes)
        chunks.append(chunk.content)
        # Break early; presence of at least one content chunk is sufficient
        if len(chunks) >= 1:
            break

    assert chunks, "Expected at least one streamed chunk"
    # Content is normalized to SSE-compatible string starting with 'data: '
    first = chunks[0].decode("utf-8") if isinstance(chunks[0], bytes) else chunks[0]
    assert first.startswith("data: ")
    assert "Hello stream" in first
