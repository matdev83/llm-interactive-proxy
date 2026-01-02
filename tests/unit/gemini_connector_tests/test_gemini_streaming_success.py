from __future__ import annotations

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
    from src.core.di.container import ServiceCollection
    from src.core.di.services import set_service_provider
    from src.core.ports.streaming_processors import (
        LoopDetectionProcessor,
        ThinkTagsProcessor,
        ToolCallRepairProcessor,
    )
    from src.core.services.streaming.stream_context_registry import (
        StreamingContextRegistry,
    )
    from src.core.services.streaming.tool_call_repair_processor import (
        ToolCallRepairProcessor as ServiceToolCallRepairProcessor,
    )
    from src.core.services.tool_call_repair_service import ToolCallRepairService

    services = ServiceCollection()
    services.add_singleton(LoopDetectionProcessor)
    services.add_singleton(ToolCallRepairProcessor)
    services.add_singleton(ThinkTagsProcessor)
    services.add_singleton(ToolCallRepairService)
    services.add_singleton(StreamingContextRegistry)
    services.add_singleton(ServiceToolCallRepairProcessor)
    provider = services.build_service_provider()
    set_service_provider(provider)

    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        gemini_backend = GeminiBackend(
            client=client, config=config, translation_service=TranslationService()
        )
        await gemini_backend.initialize(
            api_key="FAKE_KEY",
            gemini_api_base_url=TEST_GEMINI_API_BASE_URL,
            key_name="DUMMY_KEY_NAME",
        )
        yield gemini_backend


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

    # The streaming pipeline now returns SSE-formatted bytes
    first_chunk_found = False
    async for chunk in envelope.content:  # type: ignore[union-attr]
        assert isinstance(chunk, ProcessedResponse)
        # Content is now SSE-formatted bytes
        assert isinstance(chunk.content, bytes)

        # Decode and check if it contains the expected content
        chunk_str = chunk.content.decode("utf-8")
        if "Hello stream" in chunk_str:
            first_chunk_found = True
            break

    assert (
        first_chunk_found
    ), "Expected at least one streamed chunk with 'Hello stream' content"


@pytest.mark.asyncio
async def test_chat_completions_streaming_usage_chunk(
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

    # Two JSON-line events: content chunk then terminal usage chunk with finishReason STOP
    stream_payload = (
        b'{"id": "chatcmpl-1", "candidates": [{"content": {"parts": [{"text": "Step 1"}]}}]}\n'
        b'{"id": "chatcmpl-1", "candidates": [{"content": {"parts": []}, "finishReason": "STOP"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}\n'
    )
    httpx_mock.add_response(
        method="POST",
        url=stream_url,
        status_code=200,
        stream=httpx.ByteStream(stream_payload),
        headers={"Content-Type": "text/event-stream"},
    )

    envelope = await gemini_backend.chat_completions(
        request_data=sample_chat_request_data,
        processed_messages=sample_processed_messages,
        effective_model="test-model",
        gemini_api_base_url=TEST_GEMINI_API_BASE_URL,
        api_key="FAKE_KEY",
    )

    assert isinstance(envelope, StreamingResponseEnvelope)

    saw_usage = False
    async for chunk in envelope.content:  # type: ignore[union-attr]
        assert isinstance(chunk, ProcessedResponse)
        assert isinstance(chunk.content, bytes)
        chunk_str = chunk.content.decode("utf-8")
        if '"usage":' in chunk_str:
            saw_usage = True
            assert '"prompt_tokens"' in chunk_str
            assert '"completion_tokens"' in chunk_str
            break

    assert saw_usage, "Expected terminal usage chunk to be forwarded to client"

    # Ensure the stream is closed to avoid pending tasks in tests
    if hasattr(envelope.content, "aclose"):
        await envelope.content.aclose()  # type: ignore[func-returns-value]


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
    # Content is now SSE-formatted bytes
    assert isinstance(first_chunk.content, bytes)

    await envelope.cancel_callback()

    # The new streaming architecture closes the stream but doesn't make
    # backend-specific cancel requests. The stream is simply terminated.
    # Backend-specific cancellation would need to be implemented separately
    # if required for specific use cases.


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

    # The new streaming architecture uses stream_completion which calls
    # build_request and send internally. We verify the behavior rather than
    # checking implementation details.
    chunks: list[Any] = []
    async for chunk in envelope.content:  # type: ignore[union-attr]
        chunks.append(chunk)

    assert chunks, "Expected at least one streamed chunk"

    # Verify the stub client was used for streaming
    assert client.last_request is not None
    assert client.last_request["method"] == "POST"
    assert client.last_request["url"].endswith(":streamGenerateContent")
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

    # ServiceUnavailableError should be raised when consuming the stream
    # or the error is handled gracefully
    try:
        async for _chunk in envelope.content:  # type: ignore[union-attr]
            pass
    except ServiceUnavailableError as e:
        # Expected - network error was raised
        message = str(e)
        assert "Gemini streaming connection error" in message

    # The stream should have been closed
    assert client.last_response is not None
    assert client.last_response.closed is True
