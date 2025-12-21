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
