"""Tests for StreamingResponseBuilder."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

from src.core.domain.responses import StreamingResponseEnvelope
from src.core.transport.fastapi.adapters.response.streaming_response_builder import (
    StreamingResponseBuilder,
)
from src.core.transport.fastapi.adapters.sse.formatter import SSEFormatter
from starlette.responses import StreamingResponse


class TestStreamingResponseBuilder:
    """Test StreamingResponseBuilder implementation."""

    async def test_build_media_type_is_text_event_stream(self) -> None:
        """Test that media type is set to text/event-stream."""
        builder = StreamingResponseBuilder()

        async def content_gen() -> AsyncIterator[bytes]:
            yield b"data: test\n\n"

        envelope = StreamingResponseEnvelope(
            content=content_gen(),
            headers={},
            media_type="text/event-stream",
        )

        response = builder.build(envelope)

        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"

    async def test_build_null_content_produces_empty_iterator(self) -> None:
        """Test that null content produces empty iterator."""
        builder = StreamingResponseBuilder()
        envelope = StreamingResponseEnvelope(
            content=None,
            headers={},
            media_type="text/event-stream",
        )

        response = builder.build(envelope)

        assert isinstance(response, StreamingResponse)
        # Consume the iterator to verify it's empty
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        assert len(chunks) == 0

    async def test_build_headers_are_passed_through(self) -> None:
        """Test that headers are passed through."""
        builder = StreamingResponseBuilder()

        async def content_gen() -> AsyncIterator[bytes]:
            yield b"data: test\n\n"

        envelope = StreamingResponseEnvelope(
            content=content_gen(),
            headers={"x-custom-header": "value"},
            media_type="text/event-stream",
        )

        response = builder.build(envelope)

        assert isinstance(response, StreamingResponse)
        assert response.headers["x-custom-header"] == "value"

    async def test_build_status_code_is_set_correctly(self) -> None:
        """Test that status code is set correctly."""
        builder = StreamingResponseBuilder()

        async def content_gen() -> AsyncIterator[bytes]:
            yield b"data: test\n\n"

        envelope = StreamingResponseEnvelope(
            content=content_gen(),
            headers={},
            media_type="text/event-stream",
            status_code=201,
        )

        response = builder.build(envelope)

        assert isinstance(response, StreamingResponse)
        assert response.status_code == 201

    async def test_build_di_injection_works(self) -> None:
        """Test that DI injection works for SSEFormatter."""
        mock_formatter = MagicMock(spec=SSEFormatter)
        mock_formatter.format_chunk.side_effect = lambda x: (
            b"data: " + str(x).encode() + b"\n\n"
        )

        builder = StreamingResponseBuilder(sse_formatter=mock_formatter)

        async def content_gen() -> AsyncIterator[bytes]:
            yield b"test"

        envelope = StreamingResponseEnvelope(
            content=content_gen(),
            headers={},
            media_type="text/event-stream",
        )

        response = builder.build(envelope)

        assert isinstance(response, StreamingResponse)

    async def test_build_default_instance_created(self) -> None:
        """Test that default SSEFormatter instance is created."""
        builder = StreamingResponseBuilder()

        # Should not raise
        assert builder._sse_formatter is not None

    async def test_build_with_async_iterator_content(self) -> None:
        """Test building with async iterator content."""
        builder = StreamingResponseBuilder()

        async def content_gen() -> AsyncIterator[bytes]:
            yield b"data: chunk1\n\n"
            yield b"data: chunk2\n\n"

        envelope = StreamingResponseEnvelope(
            content=content_gen(),
            headers={},
            media_type="text/event-stream",
        )

        response = builder.build(envelope)

        assert isinstance(response, StreamingResponse)
        # Consume iterator to verify content
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        assert len(chunks) == 2
