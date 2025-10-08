from __future__ import annotations

"""
Tests for OpenAIConnector streaming response handling.

This module tests the chat_completions method of the OpenAIConnector class,
covering the various ways it can handle streaming responses.
"""

import json
import types
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from src.connectors.openai import OpenAIConnector

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)


class MockResponse:
    """Mock response for testing."""

    def __init__(
        self,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        is_error: bool = False,
    ) -> None:
        self.status_code: int = status_code
        self._headers: dict[str, str] = headers or {}
        self._content: bytes = content or b"test content"
        self._is_error: bool = is_error
        self._closed: bool = False
        self._aiter_bytes: Callable[..., Any] | None = None

    @property
    def headers(self) -> dict[str, str]:
        return self._headers

    @headers.setter
    def headers(self, value: dict[str, str]) -> None:
        self._headers = value

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def is_error(self) -> bool:
        return self._is_error

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def aiter_bytes(self) -> Callable[..., Any] | None:
        return self._aiter_bytes

    @aiter_bytes.setter
    def aiter_bytes(self, value: Callable[..., Any] | None) -> None:
        self._aiter_bytes = value

    async def aread(self) -> bytes:
        """Mock aread method."""
        return self._content

    async def aclose(self) -> None:
        """Mock aclose method."""
        self._closed = True

    async def __aenter__(self) -> MockResponse:
        """Async context manager entry point."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Async context manager exit point."""
        await self.aclose()

    def aiter_text(self) -> Any:
        """Mock aiter_text method that converts bytes to text."""
        aiter_bytes_callable = self.aiter_bytes
        if aiter_bytes_callable:
            # Convert bytes iterator to text iterator
            async def text_generator():
                async for chunk in aiter_bytes_callable():
                    if isinstance(chunk, bytes):
                        yield chunk.decode("utf-8")
                    else:
                        yield str(chunk)

            return text_generator()
        return None


class AsyncIterBytes:
    """Mock async iterator for bytes."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.index = 0

    def __aiter__(self) -> AsyncIterBytes:
        return self

    async def __anext__(self) -> bytes:
        if self.index >= len(self.chunks):
            raise StopAsyncIteration
        chunk = self.chunks[self.index]
        self.index += 1
        return chunk


class SyncIterBytes:
    """Mock sync iterator for bytes that also supports async iteration."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.index = 0

    def __iter__(self) -> SyncIterBytes:
        return self

    def __next__(self) -> bytes:
        if self.index >= len(self.chunks):
            raise StopIteration
        chunk = self.chunks[self.index]
        self.index += 1
        return chunk

    def __aiter__(self) -> SyncIterBytes:
        """Support async iteration."""
        return self

    async def __anext__(self) -> bytes:
        """Support async iteration."""
        if self.index >= len(self.chunks):
            raise StopAsyncIteration
        chunk = self.chunks[self.index]
        self.index += 1
        return chunk


@pytest.fixture
def connector(mocker: MockerFixture) -> OpenAIConnector:
    """Create a connector with a mock client, patching httpx.AsyncClient."""
    # Mock httpx.AsyncClient directly to ensure all instantiations are mocked
    mock_async_client = mocker.patch("httpx.AsyncClient", autospec=True)
    mock_instance = mock_async_client.return_value
    # Default mock response - make sure headers is a dict
    default_mock_response = MagicMock()
    default_mock_response.status_code = 200
    default_mock_response.headers = {}  # Ensure headers is a dict
    default_mock_response.json.return_value = {}  # Ensure json() returns a dict
    default_mock_response.text.return_value = ""  # Ensure text() returns a string
    default_mock_response.aread.return_value = b""  # Ensure aread() returns bytes
    default_mock_response.aclose = AsyncMock()
    default_mock_response.aiter_bytes = AsyncMock(return_value=[])
    default_mock_response.aiter_text = AsyncMock(return_value=[])

    mock_instance.send.return_value = default_mock_response

    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    # Disable JSON repair for streaming tests to test basic functionality
    config.session.json_repair_enabled = False
    # Pass translation_service to OpenAIConnector
    translation_service = TranslationService()
    connector = OpenAIConnector(
        mock_instance, config=config, translation_service=translation_service
    )
    connector.api_key = "test-api-key"
    return connector


@pytest.mark.asyncio
async def test_streaming_response_async_iterator(
    connector: OpenAIConnector, mocker: MockerFixture
) -> None:
    """Test handling a streaming response with an async iterator."""
    # Create a mock response with an async iterator
    chunk1 = {
        "id": "chatcmpl-123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "Hello"},
                "finish_reason": None,
            }
        ],
    }
    chunk2 = {
        "id": "chatcmpl-123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "test-model",
        "choices": [
            {"index": 0, "delta": {"content": " world"}, "finish_reason": None}
        ],
    }
    chunks = [
        f"data: {json.dumps(chunk1)}\n\n",
        f"data: {json.dumps(chunk2)}\n\n",
        "data: [DONE]\n\n",
    ]
    mock_response = MockResponse(headers={"Content-Type": "text/event-stream"})
    mock_response.aiter_bytes = lambda: AsyncIterBytes(
        [c.encode("utf-8") for c in chunks]
    )

    # Mock the client.send method to return our mock response
    mocker.patch.object(connector.client, "send", AsyncMock(return_value=mock_response))
    mocker.patch.object(
        connector.translation_service,
        "to_domain_stream_chunk",
        side_effect=lambda chunk, _: chunk,
    )

    # Create a mock ChatRequest with streaming enabled
    from src.core.domain.chat import ChatMessage, ChatRequest

    request_data = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="test")],
        stream=True,
    )

    # Call the method
    result = await connector.chat_completions(
        request_data, [{"role": "user", "content": "test"}], "test-model"
    )

    # Check the result
    from src.core.domain.responses import StreamingResponseEnvelope

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.media_type == "text/event-stream"

    # Collect the chunks from the streaming response
    collected_content = []
    async for chunk in result.content:
        if not chunk.content:
            continue
        # The content is a string, so we need to parse it as JSON
        if isinstance(chunk.content, str) and chunk.content.startswith("data:"):
            data_str = chunk.content[len("data: ") :]
            if data_str.strip() == "[DONE]":
                continue
            data = json.loads(data_str)
            choices = data.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta")
            if not delta:
                continue
            content = delta.get("content")
            if content:
                collected_content.append(content)

    full_content = "".join(collected_content)

    # Verify the chunks
    assert full_content == "Hello world"
    assert mock_response.closed


@pytest.mark.asyncio
async def test_streaming_response_sync_iterator(
    connector: OpenAIConnector, mocker: MockerFixture
) -> None:
    """Test handling a streaming response with a sync iterator."""
    # Create a mock response with a sync iterator
    chunk1 = {
        "id": "chatcmpl-123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "Hello"},
                "finish_reason": None,
            }
        ],
    }
    chunk2 = {
        "id": "chatcmpl-123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "test-model",
        "choices": [
            {"index": 0, "delta": {"content": " world"}, "finish_reason": None}
        ],
    }
    chunks = [
        f"data: {json.dumps(chunk1)}\n\n",
        f"data: {json.dumps(chunk2)}\n\n",
        "data: [DONE]\n\n",
    ]
    mock_response = MockResponse(headers={"Content-Type": "text/event-stream"})
    mock_response.aiter_bytes = lambda: SyncIterBytes(
        [c.encode("utf-8") for c in chunks]
    )

    # Mock the client.send method to return our mock response
    mocker.patch.object(connector.client, "send", AsyncMock(return_value=mock_response))
    mocker.patch.object(
        connector.translation_service,
        "to_domain_stream_chunk",
        side_effect=lambda chunk, _: chunk,
    )

    # Create a mock ChatRequest with streaming enabled
    from src.core.domain.chat import ChatMessage, ChatRequest

    request_data = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="test")],
        stream=True,
    )

    # Call the method
    result = await connector.chat_completions(
        request_data, [{"role": "user", "content": "test"}], "test-model"
    )

    # Check the result
    from src.core.domain.responses import StreamingResponseEnvelope

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.media_type == "text/event-stream"

    # Collect the chunks from the streaming response
    collected_content = []
    async for chunk in result.content:
        if not chunk.content:
            continue
        # The content is a string, so we need to parse it as JSON
        if isinstance(chunk.content, str) and chunk.content.startswith("data:"):
            data_str = chunk.content[len("data: ") :]
            if data_str.strip() == "[DONE]":
                continue
            data = json.loads(data_str)
            choices = data.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta")
            if not delta:
                continue
            content = delta.get("content")
            if content:
                collected_content.append(content)

    full_content = "".join(collected_content)

    # Verify the chunks
    assert full_content == "Hello world"
    assert mock_response.closed


@pytest.mark.asyncio
async def test_streaming_response_coroutine(
    connector: OpenAIConnector, mocker: MockerFixture
) -> None:
    """Test handling a streaming response with a coroutine."""
    # Create a mock response with a coroutine that returns an iterable
    chunk1 = {
        "id": "chatcmpl-123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": "Hello"},
                "finish_reason": None,
            }
        ],
    }
    chunk2 = {
        "id": "chatcmpl-123",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "test-model",
        "choices": [
            {"index": 0, "delta": {"content": " world"}, "finish_reason": None}
        ],
    }
    chunks = [
        f"data: {json.dumps(chunk1)}\n\n",
        f"data: {json.dumps(chunk2)}\n\n",
        "data: [DONE]\n\n",
    ]
    mock_response = MockResponse(headers={"Content-Type": "text/event-stream"})

    async def mock_aiter_bytes():
        for chunk in chunks:
            yield chunk.encode("utf-8")

    mock_response.aiter_bytes = mock_aiter_bytes

    # Mock the client.send method to return our mock response
    mocker.patch.object(connector.client, "send", AsyncMock(return_value=mock_response))
    mocker.patch.object(
        connector.translation_service,
        "to_domain_stream_chunk",
        side_effect=lambda chunk, _: chunk,
    )
    # Create a mock ChatRequest with streaming enabled
    from src.core.domain.chat import ChatMessage, ChatRequest

    request_data = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="test")],
        stream=True,
    )

    # Call the method
    result = await connector.chat_completions(
        request_data, [{"role": "user", "content": "test"}], "test-model"
    )

    # Check the result
    from src.core.domain.responses import StreamingResponseEnvelope

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.media_type == "text/event-stream"

    # Collect the chunks from the streaming response
    collected_content = []
    async for chunk in result.content:
        if not chunk.content:
            continue
        # The content is a string, so we need to parse it as JSON
        if isinstance(chunk.content, str) and chunk.content.startswith("data:"):
            data_str = chunk.content[len("data: ") :]
            if data_str.strip() == "[DONE]":
                continue
            data = json.loads(data_str)
            choices = data.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta")
            if not delta:
                continue
            content = delta.get("content")
            if content:
                collected_content.append(content)

    full_content = "".join(collected_content)

    # Verify the chunks
    assert full_content == "Hello world"
    assert mock_response.closed


@pytest.mark.asyncio
async def test_streaming_response_error(
    connector: OpenAIConnector, mocker: MockerFixture
) -> None:
    """Test handling a streaming response with an error."""
    # Create a mock response with an error
    mock_response = MockResponse(
        status_code=400, content=b'{"error": "Bad request"}', is_error=True
    )

    # Mock the client.send method to return our mock response
    mocker.patch.object(connector.client, "send", AsyncMock(return_value=mock_response))

    # Create a mock ChatRequest with streaming enabled
    from src.core.domain.chat import ChatMessage, ChatRequest

    request_data = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="test")],
        stream=True,
    )

    # Call the method and expect an exception
    with pytest.raises(HTTPException) as excinfo:
        await connector.chat_completions(
            request_data, [{"role": "user", "content": "test"}], "test-model"
        )

    # Verify the exception
    assert excinfo.value.status_code == 400
    assert "Bad request" in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_streaming_response_no_auth(connector: OpenAIConnector) -> None:
    """Test handling a streaming response with no auth."""
    # Create a mock ChatRequest with streaming enabled
    from src.core.domain.chat import ChatMessage, ChatRequest

    request_data = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="test")],
        stream=True,
    )

    # Remove the api key to trigger the auth error
    connector.api_key = None

    # Call the method with no auth and expect an exception
    with pytest.raises(HTTPException) as excinfo:
        await connector.chat_completions(
            request_data, [{"role": "user", "content": "test"}], "test-model"
        )

    # Verify the exception
    assert excinfo.value.status_code == 401
    assert "No auth credentials found" in str(excinfo.value.detail)


@pytest.mark.asyncio
async def test_identity_headers_reset_between_calls() -> None:
    """Ensure identity-specific headers do not persist between requests."""

    response_payload = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hello"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/json"}
    mock_response.json.return_value = response_payload

    post_mock = AsyncMock(return_value=mock_response)

    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    from src.core.domain.chat import ChatMessage, ChatRequest

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="ping")],
        stream=False,
    )

    client = MagicMock()
    client.post = post_mock

    connector = OpenAIConnector(
        client=client,
        config=AppConfig(),
        translation_service=TranslationService(),
    )
    connector.api_key = "test-api-key"
    connector.disable_health_check()

    class IdentityStub:
        def get_resolved_headers(self, _request: Any) -> dict[str, str]:
            return {"X-Identity": "alpha"}

    await connector.chat_completions(
        request,
        request.messages,
        "gpt-4",
        identity=IdentityStub(),
    )
    await connector.chat_completions(
        request,
        request.messages,
        "gpt-4",
        identity=None,
    )

    assert len(post_mock.await_args_list) == 2
    first_headers = post_mock.await_args_list[0].kwargs["headers"]
    second_headers = post_mock.await_args_list[1].kwargs["headers"]

    assert first_headers.get("X-Identity") == "alpha"
    assert "X-Identity" not in second_headers
    assert "Authorization" in second_headers
