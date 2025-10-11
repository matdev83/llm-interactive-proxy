from __future__ import annotations

from typing import Any

import httpx
import pytest
import pytest_asyncio

try:  # pragma: no cover - optional test dependency
    from pytest_httpx import HTTPXMock
except ModuleNotFoundError:  # pragma: no cover - optional test dependency
    HTTPXMock = None  # type: ignore[assignment]
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
@pytest.mark.skipif(HTTPXMock is None, reason="pytest_httpx not installed")
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

    first_chunk: dict[str, Any] | None = None
    async for chunk in envelope.content:  # type: ignore[union-attr]
        assert isinstance(chunk, ProcessedResponse)
        assert isinstance(chunk.content, dict)
        choices = chunk.content.get("choices", [])  # type: ignore[assignment]
        if choices:
            delta = choices[0].get("delta", {})
            if delta.get("content"):
                first_chunk = chunk.content
                break

    assert first_chunk is not None, "Expected at least one streamed chunk with content"
    first_delta = first_chunk["choices"][0]["delta"]
    assert first_delta.get("content", "").startswith("Hello")


class _StubStreamResponse:
    def __init__(self) -> None:
        self.status_code = 200
        self.headers: dict[str, str] = {"content-type": "text/event-stream"}
        self.closed = False

    def aiter_text(self) -> Any:
        async def _gen() -> Any:
            yield (
                'data: {"candidates": [{"content": {"parts": [{"text": '
                '"Hello chunk"}]}}]}\n\n'
            )

        return _gen()

    async def aclose(self) -> None:
        self.closed = True

    async def aread(self) -> bytes:
        return b""


class _StubAsyncClient:
    def __init__(self) -> None:
        self.last_stream_flag: bool | None = None
        self.last_request: dict[str, Any] | None = None
        self.last_response: _StubStreamResponse | None = None

    def build_request(
        self,
        method: str,
        url: str,
        *,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self.last_request = {
            "method": method,
            "url": url,
            "json": json,
            "headers": headers or {},
        }
        return self.last_request

    async def send(
        self, request: dict[str, Any], stream: bool = False
    ) -> _StubStreamResponse:
        self.last_stream_flag = stream
        response = _StubStreamResponse()
        self.last_response = response
        return response


@pytest.mark.asyncio
async def test_chat_completions_streaming_uses_httpx_stream_send() -> None:
    from src.core.config.app_config import AppConfig
    from src.core.domain.responses import StreamingResponseEnvelope
    from src.core.services.translation_service import TranslationService

    client = _StubAsyncClient()
    backend = GeminiBackend(
        client=client, config=AppConfig(), translation_service=TranslationService()
    )

    request = ChatRequest(
        model="gemini-pro",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
    )

    envelope = await backend.chat_completions(
        request_data=request,
        processed_messages=list(request.messages),
        effective_model="gemini/gemini-pro",
        gemini_api_base_url=TEST_GEMINI_API_BASE_URL,
        api_key="DUMMY",
    )

    assert isinstance(envelope, StreamingResponseEnvelope)
    assert client.last_stream_flag is True
    assert client.last_request is not None
    assert client.last_request["method"] == "POST"
    assert client.last_request["url"].endswith(":streamGenerateContent")

    chunks: list[Any] = []
    async for chunk in envelope.content:  # type: ignore[union-attr]
        chunks.append(chunk)

    assert chunks, "Expected at least one streamed chunk"
    assert client.last_response is not None
    assert client.last_response.closed is True
