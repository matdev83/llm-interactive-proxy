"""Tests for UsageNormalizationContext.

This module tests the usage normalization context model, including
the helper method for building from RequestContext with request_id precedence.
"""

from __future__ import annotations

from src.core.domain.request_context import ProcessingContext, RequestContext
from src.core.domain.usage_canonical_record import UsageCompletionOutcome
from src.core.domain.usage_normalization_context import UsageNormalizationContext


class TestUsageNormalizationContext:
    """Test UsageNormalizationContext model."""

    def test_basic_creation(self) -> None:
        """Test basic context creation."""
        context = UsageNormalizationContext(
            request_id="req-123",
            protocol="openai",
            backend_type="openai",
            model="gpt-4",
        )
        assert context.request_id == "req-123"
        assert context.protocol == "openai"
        assert context.backend_type == "openai"
        assert context.model == "gpt-4"

    def test_from_request_context_with_request_id(self) -> None:
        """Test building from RequestContext with request_id in RequestContext."""
        request_context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="req-primary",
        )
        context = UsageNormalizationContext.from_request_context(request_context)
        assert context.request_id == "req-primary"

    def test_from_request_context_with_processing_context_request_id(
        self,
    ) -> None:
        """Test building from RequestContext with request_id in processing_context.values."""
        processing_context = ProcessingContext()
        processing_context.values["request_id"] = "req-fallback"
        request_context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id=None,  # Primary is None
            processing_context=processing_context,
        )
        context = UsageNormalizationContext.from_request_context(request_context)
        # Should use fallback from processing_context.values
        assert context.request_id == "req-fallback"

    def test_from_request_context_request_id_precedence(self) -> None:
        """Test request_id precedence: RequestContext.request_id takes precedence."""
        processing_context = ProcessingContext()
        processing_context.values["request_id"] = "req-fallback"
        request_context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="req-primary",  # Primary exists
            processing_context=processing_context,
        )
        context = UsageNormalizationContext.from_request_context(request_context)
        # Should use primary, not fallback
        assert context.request_id == "req-primary"

    def test_from_request_context_no_request_id(self) -> None:
        """Test building from RequestContext with no request_id anywhere."""
        request_context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id=None,
            processing_context=None,
        )
        context = UsageNormalizationContext.from_request_context(request_context)
        assert context.request_id is None

    def test_from_request_context_extracts_protocol(self) -> None:
        """Test extracting protocol from RequestContext.extensions."""
        request_context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            extensions={"protocol": "anthropic"},
        )
        context = UsageNormalizationContext.from_request_context(request_context)
        assert context.protocol == "anthropic"

    def test_from_request_context_extracts_backend_and_model(self) -> None:
        """Test extracting backend_type and model from RequestContext."""
        request_context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            backend="openai",
            effective_model="gpt-4",
        )
        context = UsageNormalizationContext.from_request_context(request_context)
        assert context.backend_type == "openai"
        assert context.model == "gpt-4"

    def test_from_request_context_with_streaming_signals(self) -> None:
        """Test building context with streaming completion signals."""
        request_context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
        )
        context = UsageNormalizationContext.from_request_context(
            request_context,
            is_streaming=True,
            completion_outcome=UsageCompletionOutcome.incomplete,
            cancel_reason="client_disconnect",
            error_classification="timeout",
        )
        assert context.is_streaming is True
        assert context.completion_outcome == UsageCompletionOutcome.incomplete
        assert context.cancel_reason == "client_disconnect"
        assert context.error_classification == "timeout"

    def test_from_request_context_extracts_cancel_reason_from_processing_context(
        self,
    ) -> None:
        """Test extracting cancel_reason from processing_context.values."""
        processing_context = ProcessingContext()
        processing_context.values["cancel_reason"] = "stream_cancelled"
        request_context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            processing_context=processing_context,
        )
        context = UsageNormalizationContext.from_request_context(request_context)
        assert context.cancel_reason == "stream_cancelled"

    def test_from_request_context_cancel_reason_precedence(self) -> None:
        """Test that explicit cancel_reason parameter takes precedence."""
        processing_context = ProcessingContext()
        processing_context.values["cancel_reason"] = "stream_cancelled"
        request_context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            processing_context=processing_context,
        )
        context = UsageNormalizationContext.from_request_context(
            request_context, cancel_reason="client_disconnect"
        )
        # Explicit parameter should take precedence
        assert context.cancel_reason == "client_disconnect"
