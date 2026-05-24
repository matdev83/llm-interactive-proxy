"""Tests for ResponseEnvelope and StreamingResponseEnvelope.

This module tests the response envelope models including the canonical_usage field.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.usage_canonical_record import (
    CanonicalUsageRecord,
    UsageCompletionOutcome,
)
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestResponseEnvelope:
    """Test ResponseEnvelope model."""

    def test_create_with_canonical_usage(self) -> None:
        """Test creating ResponseEnvelope with canonical_usage."""
        canonical_usage = CanonicalUsageRecord(
            provider_id="openai",
            model_id="gpt-4",
            request_id="req-123",
            protocol="openai",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        envelope = ResponseEnvelope(
            content={"message": "test"},
            canonical_usage=canonical_usage,
        )
        assert envelope.canonical_usage == canonical_usage
        assert envelope.content == {"message": "test"}

    def test_create_without_canonical_usage(self) -> None:
        """Test creating ResponseEnvelope without canonical_usage (backward compatibility)."""
        envelope = ResponseEnvelope(content={"message": "test"})
        assert envelope.canonical_usage is None
        assert envelope.content == {"message": "test"}

    def test_canonical_usage_and_usage_coexist(self) -> None:
        """Test that canonical_usage and usage fields can coexist."""
        canonical_usage = CanonicalUsageRecord(
            provider_id="openai",
            model_id="gpt-4",
            prompt_tokens=100,
            completion_tokens=50,
        )
        usage_summary = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        envelope = ResponseEnvelope(
            content={"message": "test"},
            usage=usage_summary,
            canonical_usage=canonical_usage,
        )
        assert envelope.usage == usage_summary
        assert envelope.canonical_usage == canonical_usage

    def test_backward_compatibility_existing_fields(self) -> None:
        """Test that existing fields remain unchanged for backward compatibility."""
        usage_summary = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        envelope = ResponseEnvelope(
            content={"message": "test"},
            headers={"X-Custom": "value"},
            status_code=201,
            media_type="application/json",
            usage=usage_summary,
            metadata={"key": "value"},
        )
        assert envelope.content == {"message": "test"}
        assert envelope.headers == {"X-Custom": "value"}
        assert envelope.status_code == 201
        assert envelope.media_type == "application/json"
        assert envelope.usage == usage_summary
        assert envelope.metadata == {"key": "value"}
        assert envelope.canonical_usage is None


class TestStreamingResponseEnvelope:
    """Test StreamingResponseEnvelope model."""

    @pytest.fixture
    def mock_iterator(self) -> AsyncIterator[ProcessedResponse]:
        """Create a mock async iterator."""

        async def _iterator() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content=b"chunk1")
            yield ProcessedResponse(content=b"chunk2")

        return _iterator()

    def test_create_with_canonical_usage(
        self, mock_iterator: AsyncIterator[ProcessedResponse]
    ) -> None:
        """Test creating StreamingResponseEnvelope with canonical_usage."""
        canonical_usage = CanonicalUsageRecord(
            provider_id="anthropic",
            model_id="claude-3-5-sonnet",
            request_id="req-456",
            protocol="anthropic",
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            completion_outcome=UsageCompletionOutcome.complete,
        )
        envelope = StreamingResponseEnvelope(
            content=mock_iterator,
            canonical_usage=canonical_usage,
        )
        assert envelope.canonical_usage == canonical_usage
        assert envelope.content == mock_iterator

    def test_create_without_canonical_usage(
        self, mock_iterator: AsyncIterator[ProcessedResponse]
    ) -> None:
        """Test creating StreamingResponseEnvelope without canonical_usage (backward compatibility)."""
        envelope = StreamingResponseEnvelope(content=mock_iterator)
        assert envelope.canonical_usage is None
        assert envelope.content == mock_iterator

    def test_backward_compatibility_existing_fields(
        self, mock_iterator: AsyncIterator[ProcessedResponse]
    ) -> None:
        """Test that existing fields remain unchanged for backward compatibility."""
        cancel_callback = AsyncMock()

        envelope = StreamingResponseEnvelope(
            content=mock_iterator,
            media_type="text/event-stream",
            headers={"X-Custom": "value"},
            status_code=200,
            cancel_callback=cancel_callback,
            metadata={"key": "value"},
        )
        assert envelope.content == mock_iterator
        assert envelope.media_type == "text/event-stream"
        assert envelope.headers == {"X-Custom": "value"}
        assert envelope.status_code == 200
        assert envelope.cancel_callback == cancel_callback
        assert envelope.metadata == {"key": "value"}
        assert envelope.canonical_usage is None

    @pytest.mark.asyncio
    async def test_body_iterator_indented_data_not_treated_as_sse(self) -> None:
        """Test that indented data: is NOT treated as already SSE-formatted."""

        async def _iterator() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content=b"  data: hi\n\n")

        envelope = StreamingResponseEnvelope(
            content=_iterator(),
            media_type="text/event-stream",
        )

        chunks = []
        async for chunk in envelope.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == 1
        # Should be framed (starts with "data: "), not passed through unchanged
        assert chunks[0].startswith(b"data: "), "Indented data: should be framed"
        # The indented "  data: hi\n\n" has two lines: "  data: hi" and "" (empty)
        # So it becomes "data:   data: hi\ndata: \n\n"
        assert chunks[0] == b"data:   data: hi\ndata: \n\n"

    @pytest.mark.asyncio
    async def test_body_iterator_later_line_data_not_fool_detection(self) -> None:
        """Test that data: on later line does NOT fool 'already SSE' detection."""

        async def _iterator() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content=b"hello\n data: hi\n")

        envelope = StreamingResponseEnvelope(
            content=_iterator(),
            media_type="text/event-stream",
        )

        chunks = []
        async for chunk in envelope.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == 1
        # First non-empty line is "hello", so should be framed
        assert chunks[0].startswith(
            b"data: hello"
        ), "Should frame starting with first line"
        assert b"data: hello" in chunks[0]

    @pytest.mark.asyncio
    async def test_body_iterator_already_sse_bytes_pass_through(self) -> None:
        """Test that already SSE-formatted bytes pass through unchanged."""

        async def _iterator() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content=b"event: ping\ndata: ok\n\n")

        envelope = StreamingResponseEnvelope(
            content=_iterator(),
            media_type="text/event-stream",
        )

        chunks = []
        async for chunk in envelope.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == 1
        # Should pass through unchanged (no double framing)
        assert chunks[0] == b"event: ping\ndata: ok\n\n"

    @pytest.mark.asyncio
    async def test_body_iterator_already_sse_str_pass_through(self) -> None:
        """Test that already SSE-formatted string passes through unchanged."""

        async def _iterator() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content="data: ok\n\n")

        envelope = StreamingResponseEnvelope(
            content=_iterator(),
            media_type="text/event-stream",
        )

        chunks = []
        async for chunk in envelope.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == 1
        # Should pass through unchanged (no double framing)
        assert (
            chunks[0] == b"data: ok\n\n"
        ), f"Should not double-frame: got {chunks[0]!r}"

    @pytest.mark.asyncio
    async def test_body_iterator_multi_line_payload_framing(self) -> None:
        """Test that multi-line payloads are split into multiple data: lines."""

        async def _iterator() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content="a\nb")

        envelope = StreamingResponseEnvelope(
            content=_iterator(),
            media_type="text/event-stream",
        )

        chunks = []
        async for chunk in envelope.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == 1
        # Should be split into multiple data: lines
        assert chunks[0] == b"data: a\ndata: b\n\n"

    @pytest.mark.asyncio
    async def test_body_iterator_non_sse_media_type_no_framing(self) -> None:
        """Test that non-SSE media types don't apply SSE framing."""

        async def _iterator() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content={"test": "value"})

        envelope = StreamingResponseEnvelope(
            content=_iterator(),
            media_type="application/json",
        )

        chunks = []
        async for chunk in envelope.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == 1
        # Should be JSON without SSE framing
        decoded = chunks[0].decode("utf-8")
        assert not decoded.startswith("data: "), "Non-SSE should not have SSE framing"
        import json

        assert json.loads(decoded) == {"test": "value"}

    @pytest.mark.asyncio
    async def test_body_iterator_dict_sse_framing(self) -> None:
        """Test that dict chunks are JSON-serialized and SSE-framed for SSE media type."""

        async def _iterator() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content={"message": "hello", "number": 42})

        envelope = StreamingResponseEnvelope(
            content=_iterator(),
            media_type="text/event-stream",
        )

        chunks = []
        async for chunk in envelope.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == 1
        # Should be SSE-framed JSON
        decoded = chunks[0].decode("utf-8")
        assert decoded.startswith("data: {"), "Dict should be SSE-framed"
        assert decoded.endswith("\n\n"), "Should end with \\n\\n"
        import json

        json_content = decoded[6:-2]  # Remove "data: " and "\n\n"
        assert json.loads(json_content) == {"message": "hello", "number": 42}
