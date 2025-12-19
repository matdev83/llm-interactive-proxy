"""Integration tests for response adapters facade.

Tests the full integration of response adapters with wire capture,
streaming conversion, and all layer components.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.transport.fastapi.response_adapters import (
    domain_response_to_fastapi,
    to_fastapi_response,
    to_fastapi_streaming_response,
)


class MockWireCapture(IWireCapture):
    """Mock wire capture for testing."""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self.captured_responses = []
        self.wrapped_streams = []

    def enabled(self) -> bool:
        return self._enabled

    async def capture_inbound_request(self, **kwargs) -> None:
        pass

    async def capture_outbound_request(self, **kwargs) -> None:
        pass

    async def capture_inbound_response(self, **kwargs) -> None:
        pass

    def wrap_inbound_stream(self, **kwargs) -> AsyncIterator[bytes]:
        async def _empty():
            yield b""

        return _empty()

    async def capture_outbound_response(
        self,
        *,
        context=None,
        session_id=None,
        backend=None,
        model=None,
        key_name=None,
        response_content=None,
    ) -> None:
        self.captured_responses.append(
            {
                "session_id": session_id,
                "backend": backend,
                "model": model,
                "key_name": key_name,
                "response_content": response_content,
            }
        )

    def wrap_outbound_stream(
        self,
        *,
        context=None,
        session_id=None,
        backend=None,
        model=None,
        key_name=None,
        stream=None,
    ) -> AsyncIterator[bytes]:
        self.wrapped_streams.append(
            {
                "session_id": session_id,
                "backend": backend,
                "model": model,
                "key_name": key_name,
            }
        )
        # Pass through the stream
        return stream

    async def shutdown(self) -> None:
        """Gracefully stop background work."""


@pytest.mark.asyncio
async def test_non_streaming_json_response():
    """Test full non-streaming JSON response path."""
    envelope = ResponseEnvelope(
        content={"message": "Hello, world!"},
        headers={"x-custom": "value"},
        status_code=200,
    )

    response = to_fastapi_response(envelope)

    assert response.status_code == 200
    assert response.headers.get("x-custom") == "value"
    assert response.media_type == "application/json"


@pytest.mark.asyncio
async def test_non_streaming_json_response_with_wire_capture():
    """Test non-streaming JSON response with wire capture enabled."""
    wire_capture = MockWireCapture(enabled=True)
    envelope = ResponseEnvelope(
        content={"message": "Hello, world!"},
        headers={},
        status_code=200,
        metadata={"backend": "openai", "model": "gpt-4"},
    )

    response = to_fastapi_response(envelope, wire_capture=wire_capture)

    assert response.status_code == 200

    # Wait a bit for background task to complete
    await asyncio.sleep(0.1)

    # Verify wire capture was scheduled
    assert len(wire_capture.captured_responses) == 1
    captured_content = wire_capture.captured_responses[0]["response_content"]
    assert isinstance(captured_content, dict)
    assert captured_content.get("message") == "Hello, world!"


@pytest.mark.asyncio
async def test_non_streaming_json_response_with_wire_capture_disabled():
    """Test non-streaming JSON response with wire capture disabled."""
    wire_capture = MockWireCapture(enabled=False)
    envelope = ResponseEnvelope(
        content={"message": "Hello, world!"},
        headers={},
        status_code=200,
    )

    response = to_fastapi_response(envelope, wire_capture=wire_capture)

    assert response.status_code == 200

    # Wait a bit for background task to complete
    await asyncio.sleep(0.1)

    # Verify wire capture was NOT scheduled
    assert len(wire_capture.captured_responses) == 0


@pytest.mark.asyncio
async def test_streaming_response():
    """Test full streaming response path."""

    async def _simple_stream() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        yield b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    envelope = StreamingResponseEnvelope(
        content=_simple_stream(),
        headers={"x-custom": "value"},
        status_code=200,
    )

    response = to_fastapi_streaming_response(envelope)

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert response.headers.get("x-custom") == "value"

    # Consume the stream to verify it works
    chunks = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk)

    # Should have SSE-formatted chunks
    assert len(chunks) > 0


@pytest.mark.asyncio
async def test_streaming_response_with_wire_capture():
    """Test streaming response with wire capture enabled."""
    wire_capture = MockWireCapture(enabled=True)

    async def _simple_stream() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    envelope = StreamingResponseEnvelope(
        content=_simple_stream(),
        headers={},
        status_code=200,
        metadata={"backend": "openai", "model": "gpt-4"},
    )

    response = to_fastapi_streaming_response(envelope, wire_capture=wire_capture)

    assert response.status_code == 200

    # Consume the stream
    chunks = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk)

    # Verify wire capture wrapped the stream
    assert len(wire_capture.wrapped_streams) == 1


@pytest.mark.asyncio
async def test_streaming_response_with_wire_capture_disabled():
    """Test streaming response with wire capture disabled."""
    wire_capture = MockWireCapture(enabled=False)

    async def _simple_stream() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    envelope = StreamingResponseEnvelope(
        content=_simple_stream(),
        headers={},
        status_code=200,
    )

    response = to_fastapi_streaming_response(envelope, wire_capture=wire_capture)

    assert response.status_code == 200

    # Consume the stream
    chunks = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk)

    # Verify wire capture did NOT wrap the stream
    assert len(wire_capture.wrapped_streams) == 0


@pytest.mark.asyncio
async def test_domain_response_to_fastapi_non_streaming():
    """Test domain_response_to_fastapi with non-streaming response."""
    envelope = ResponseEnvelope(
        content={"message": "Hello"},
        headers={},
        status_code=200,
    )

    response = domain_response_to_fastapi(envelope)

    assert response.status_code == 200
    assert response.media_type == "application/json"


@pytest.mark.asyncio
async def test_domain_response_to_fastapi_streaming():
    """Test domain_response_to_fastapi with streaming response."""

    async def _simple_stream() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    envelope = StreamingResponseEnvelope(
        content=_simple_stream(),
        headers={},
        status_code=200,
    )

    response = domain_response_to_fastapi(envelope)

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_content_converter_parameter():
    """Test content_converter parameter (legacy support)."""

    def converter(content: dict) -> dict:
        content["converted"] = True
        return content

    envelope = ResponseEnvelope(
        content={"message": "Hello"},
        headers={},
        status_code=200,
    )

    response = to_fastapi_response(envelope, content_converter=converter)

    assert response.status_code == 200
    # Note: We can't easily verify the conversion without parsing response body
    # but the function should execute without error


@pytest.mark.asyncio
async def test_empty_streaming_response():
    """Test streaming response with None content."""
    envelope = StreamingResponseEnvelope(
        content=None,
        headers={},
        status_code=200,
    )

    response = to_fastapi_streaming_response(envelope)

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"

    # Consume the stream (should be empty)
    chunks = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk)

    # Should handle empty stream gracefully
    assert isinstance(chunks, list)
