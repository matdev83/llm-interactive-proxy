from __future__ import annotations

"""
Tests for OpenAIConnector streaming response handling.

This module tests the chat_completions method of the OpenAIConnector class,
covering the various ways it can handle streaming responses.
"""

import types
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from src.connectors.openai import OpenAIConnector

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


class MockResponse:
    """Mock response for testing."""

    def __init__(
        self,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        is_error: bool = False,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content or b"test content"
        self.is_error = is_error
        self.closed = False
        self.aiter_bytes: Callable[..., Any] | None = None

    async def aread(self) -> bytes:
        """Mock aread method."""
        return self.content

    async def aclose(self) -> None:
        """Mock aclose method."""
        self.closed = True

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
    """Mock sync iterator for bytes."""

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


@pytest.fixture
def connector(mocker: MockerFixture) -> OpenAIConnector:
    """Create a connector with a mock client, patching httpx.AsyncClient."""
    # Mock httpx.AsyncClient directly to ensure all instantiations are mocked
    mock_async_client = mocker.patch("httpx.AsyncClient", autospec=True)
    mock_instance = mock_async_client.return_value
    mock_instance.send.return_value = MockResponse()  # Default mock response

    connector = OpenAIConnector(mock_instance)
    connector.api_key = "test-api-key"
    return connector


@pytest.mark.asyncio
async def test_streaming_response_async_iterator(
    connector: OpenAIConnector, mocker: MockerFixture
) -> None:
    """Test handling a streaming response with an async iterator."""
    # Create a mock response with an async iterator
    chunks = [b"chunk1", b"chunk2", b"chunk3"]
    mock_response = MockResponse(headers={"Content-Type": "text/event-stream"})
    mock_response.aiter_bytes = lambda: AsyncIterBytes(chunks)

    # Mock the client.send method to return our mock response
    mocker.patch.object(connector.client, "send", AsyncMock(return_value=mock_response))

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
    collected_chunks = []
    async for chunk in result.content:
        collected_chunks.append(chunk)

    # Verify the chunks
    assert collected_chunks == chunks
    assert mock_response.closed


@pytest.mark.asyncio
async def test_streaming_response_sync_iterator(
    connector: OpenAIConnector, mocker: MockerFixture
) -> None:
    """Test handling a streaming response with a sync iterator."""
    # Create a mock response with a sync iterator
    chunks = [b"chunk1", b"chunk2", b"chunk3"]
    mock_response = MockResponse(headers={"Content-Type": "text/event-stream"})
    mock_response.aiter_bytes = lambda: SyncIterBytes(chunks)

    # Mock the client.send method to return our mock response
    mocker.patch.object(connector.client, "send", AsyncMock(return_value=mock_response))

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
    collected_chunks = []
    async for chunk in result.content:
        collected_chunks.append(chunk)

    # Verify the chunks
    assert collected_chunks == chunks
    assert mock_response.closed


@pytest.mark.asyncio
async def test_streaming_response_coroutine(
    connector: OpenAIConnector, mocker: MockerFixture
) -> None:
    """Test handling a streaming response with a coroutine."""
    # Create a mock response with a coroutine that returns an iterable
    chunks = [b"chunk1", b"chunk2", b"chunk3"]
    mock_response = MockResponse(headers={"Content-Type": "text/event-stream"})

    async def mock_aiter_bytes() -> list[bytes]:
        return chunks

    mock_response.aiter_bytes = mock_aiter_bytes

    # Mock the client.send method to return our mock response
    mocker.patch.object(connector.client, "send", AsyncMock(return_value=mock_response))

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
    collected_chunks = []
    async for chunk in result.content:
        collected_chunks.append(chunk)

    # Verify the chunks
    assert collected_chunks == chunks
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
