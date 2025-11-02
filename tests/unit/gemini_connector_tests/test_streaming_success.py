from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock
from src.connectors.gemini import GeminiBackend
from src.core.common.exceptions import ServiceUnavailableError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse

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


@pytest.mark.asyncio
async def test_chat_completions_streaming_cancel_request(
    gemini_backend: GeminiBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: ChatRequest,
    sample_processed_messages: list[ChatMessage],
):
    sample_chat_request_data = sample_chat_request_data.model_copy(
        update={"stream": True}
    )

    stream_url = (
        f"{TEST_GEMINI_API_BASE_URL}/v1beta/models/test-model:streamGenerateContent"
    )
    httpx_mock.add_response(
        method="POST",
        url=stream_url,
        status_code=200,
        stream=httpx.ByteStream(
            b'data: {"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}\n\n'
        ),
        headers={
            "Content-Type": "text/event-stream",
            "x-goog-request-id": "req-123",
        },
    )

    cancel_url = f"{TEST_GEMINI_API_BASE_URL}/v1beta/models/test-model:cancel"
    httpx_mock.add_response(
        method="POST",
        url=cancel_url,
        status_code=200,
        json={"status": "cancelled"},
    )

    envelope = await gemini_backend.chat_completions(
        request_data=sample_chat_request_data,
        processed_messages=sample_processed_messages,
        effective_model="test-model",
        gemini_api_base_url=TEST_GEMINI_API_BASE_URL,
        api_key="FAKE_KEY",
    )

    assert isinstance(envelope, StreamingResponseEnvelope)
    assert envelope.cancel_callback is not None

    first_chunk = await envelope.content.__anext__()  # type: ignore[union-attr]
    assert isinstance(first_chunk, ProcessedResponse)

    await envelope.cancel_callback()

    cancel_requests = [
        req for req in httpx_mock.get_requests() if req.url == cancel_url
    ]
    assert cancel_requests, "Expected Gemini cancel request"
    cancel_payload = json.loads(cancel_requests[0].content)
    assert cancel_payload.get("requestId") == "req-123"


class _StubStreamResponse:
    def __init__(self) -> None:
        self.status_code = 200
        self.headers: dict[str, str] = {"content-type": "text/event-stream"}
        self.closed = False

    def aiter_text(self) -> AsyncGenerator[str, None]:
        async def _gen() -> AsyncGenerator[str, None]:
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
    def __init__(
        self,
        response_factory: Callable[[], _StubStreamResponse] | None = None,
    ) -> None:
        self.last_stream_flag: bool | None = None
        self.last_request: dict[str, Any] | None = None
        self.last_response: _StubStreamResponse | None = None
        self._response_factory = response_factory or _StubStreamResponse

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
        response = self._response_factory()
        self.last_response = response
        return response

    async def post(
        self,
        url: str,
        *,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> _StubStreamResponse:
        # Store request info for assertions
        self.last_request = {
            "method": "POST",
            "url": url,
            "json": json,
            "headers": headers or {},
        }
        # For streaming requests, set stream flag to True
        is_streaming = url.endswith(":streamGenerateContent")
        self.last_stream_flag = is_streaming
        response = self._response_factory()
        self.last_response = response
        return response


@pytest.mark.asyncio
async def test_chat_completions_streaming_uses_httpx_stream_send() -> None:
    from src.core.config.app_config import AppConfig
    from src.core.domain.responses import StreamingResponseEnvelope
    from src.core.services.translation_service import TranslationService

    client = _StubAsyncClient()
    backend = GeminiBackend(
        client=client,  # type: ignore[arg-type]
        config=AppConfig(),
        translation_service=TranslationService(),
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


class _ErrorStreamResponse(_StubStreamResponse):
    def __init__(self, request_url: str) -> None:
        super().__init__()
        self._request = httpx.Request("POST", request_url)

    def aiter_text(self) -> AsyncGenerator[str, None]:
        async def _gen() -> AsyncGenerator[str, None]:
            yield (
                'data: {"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}\n\n'
            )
            raise httpx.ReadError("stream disconnected", request=self._request)

        return _gen()


@pytest.mark.asyncio
async def test_chat_completions_streaming_network_error_translated() -> None:
    from src.core.config.app_config import AppConfig
    from src.core.domain.responses import StreamingResponseEnvelope
    from src.core.services.translation_service import TranslationService

    request = ChatRequest(
        model="gemini-pro",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
    )

    request_url = (
        f"{TEST_GEMINI_API_BASE_URL}/v1beta/models/gemini-pro:streamGenerateContent"
    )
    client = _StubAsyncClient(
        response_factory=lambda: _ErrorStreamResponse(request_url)
    )
    backend = GeminiBackend(
        client=client,  # type: ignore[arg-type]
        config=AppConfig(),
        translation_service=TranslationService(),
    )

    envelope = await backend.chat_completions(
        request_data=request,
        processed_messages=list(request.messages),
        effective_model="gemini/gemini-pro",
        gemini_api_base_url=TEST_GEMINI_API_BASE_URL,
        api_key="DUMMY",
    )

    assert isinstance(envelope, StreamingResponseEnvelope)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        async for _chunk in envelope.content:  # type: ignore[union-attr]
            pass

    message = str(exc_info.value)
    assert "Gemini streaming connection error" in message

    assert client.last_response is not None
    assert client.last_response.closed is True
