"""Tests for StreamingResponseBuilder."""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.usage_canonical_record import CanonicalUsageRecord
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

    async def test_build_canonical_usage_headers_injected(self) -> None:
        """Test that canonical usage headers are injected (Requirement 5.5)."""
        builder = StreamingResponseBuilder()

        async def content_gen() -> AsyncIterator[bytes]:
            yield b"data: test\n\n"

        canonical_usage = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            cost=0.05,
        )

        envelope = StreamingResponseEnvelope(
            content=content_gen(),
            headers={},
            media_type="text/event-stream",
            canonical_usage=canonical_usage,
        )

        response = builder.build(envelope)

        assert isinstance(response, StreamingResponse)
        # Headers should be derived from canonical usage
        assert response.headers["x-usage-prompt-tokens"] == "100"
        assert response.headers["x-usage-completion-tokens"] == "200"
        assert response.headers["x-usage-total-tokens"] == "300"
        assert response.headers["x-usage-cost"] == "0.05"

    async def test_build_canonical_usage_headers_with_extensions(self) -> None:
        """Test that extended fields from canonical usage are in headers."""
        builder = StreamingResponseBuilder()

        async def content_gen() -> AsyncIterator[bytes]:
            yield b"data: test\n\n"

        canonical_usage = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            extensions={
                "completion_tokens_details": {"reasoning_tokens": 50},
                "prompt_tokens_details": {"cached_tokens": 25},
            },
        )

        envelope = StreamingResponseEnvelope(
            content=content_gen(),
            headers={},
            media_type="text/event-stream",
            canonical_usage=canonical_usage,
        )

        response = builder.build(envelope)

        assert isinstance(response, StreamingResponse)
        # Extended fields should be in headers
        assert response.headers["x-usage-reasoning-tokens"] == "50"
        assert response.headers["x-usage-cached-tokens"] == "25"

    async def test_build_canonical_usage_headers_preserve_existing(self) -> None:
        """Test that existing headers are preserved when injecting canonical usage headers."""
        builder = StreamingResponseBuilder()

        async def content_gen() -> AsyncIterator[bytes]:
            yield b"data: test\n\n"

        canonical_usage = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
        )

        envelope = StreamingResponseEnvelope(
            content=content_gen(),
            headers={"x-custom-header": "value"},
            media_type="text/event-stream",
            canonical_usage=canonical_usage,
        )

        response = builder.build(envelope)

        assert isinstance(response, StreamingResponse)
        # Existing headers should be preserved
        assert response.headers["x-custom-header"] == "value"
        # Canonical usage headers should be added
        assert response.headers["x-usage-prompt-tokens"] == "100"
