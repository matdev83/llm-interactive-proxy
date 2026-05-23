"""Tests for content modification tracking.

This module tests the ContentModificationTracker that tracks when
content is modified during proxy processing, enabling accurate usage recalculation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from src.core.domain.request_context import (
    ContentModificationTracker,
    ProcessingContext,
    RequestContext,
)


class TestContentModificationTracker:
    """Test ContentModificationTracker functionality."""

    def test_initial_state(self) -> None:
        """Tracker should start with no modifications."""
        tracker = ContentModificationTracker()
        assert tracker.inbound_modified is False
        assert tracker.outbound_modified is False
        assert tracker.inbound_modification_reasons == []
        assert tracker.outbound_modification_reasons == []

    def test_mark_inbound_modified(self) -> None:
        """Marking inbound modified should update state."""
        tracker = ContentModificationTracker()
        tracker.mark_inbound_modified("system_prompt_injection")

        assert tracker.inbound_modified is True
        assert "system_prompt_injection" in tracker.inbound_modification_reasons

    def test_mark_inbound_modified_with_tokens(self) -> None:
        """Marking with tokens should store them."""
        tracker = ContentModificationTracker()
        tracker.mark_inbound_modified(
            reason="api_key_redaction",
            original_tokens=100,
            modified_tokens=95,
        )

        assert tracker.inbound_modified is True
        assert tracker.inbound_original_tokens == 100
        assert tracker.inbound_modified_tokens == 95

    def test_mark_outbound_modified(self) -> None:
        """Marking outbound modified should update state."""
        tracker = ContentModificationTracker()
        tracker.mark_outbound_modified("think_tag_processing")

        assert tracker.outbound_modified is True
        assert "think_tag_processing" in tracker.outbound_modification_reasons

    def test_mark_outbound_modified_with_tokens(self) -> None:
        """Marking with tokens should store them."""
        tracker = ContentModificationTracker()
        tracker.mark_outbound_modified(
            reason="content_filtering",
            original_tokens=200,
            modified_tokens=180,
        )

        assert tracker.outbound_modified is True
        assert tracker.outbound_original_tokens == 200
        assert tracker.outbound_modified_tokens == 180

    def test_multiple_inbound_reasons(self) -> None:
        """Multiple reasons should be accumulated."""
        tracker = ContentModificationTracker()
        tracker.mark_inbound_modified("reason1")
        tracker.mark_inbound_modified("reason2")
        tracker.mark_inbound_modified("reason3")

        assert len(tracker.inbound_modification_reasons) == 3
        assert "reason1" in tracker.inbound_modification_reasons
        assert "reason2" in tracker.inbound_modification_reasons
        assert "reason3" in tracker.inbound_modification_reasons

    def test_duplicate_reasons_not_added(self) -> None:
        """Duplicate reasons should not be added."""
        tracker = ContentModificationTracker()
        tracker.mark_inbound_modified("same_reason")
        tracker.mark_inbound_modified("same_reason")

        assert len(tracker.inbound_modification_reasons) == 1

    def test_requires_usage_recalculation_false(self) -> None:
        """No modifications should not require recalculation."""
        tracker = ContentModificationTracker()
        assert tracker.requires_usage_recalculation() is False

    def test_requires_usage_recalculation_inbound(self) -> None:
        """Inbound modification should require recalculation."""
        tracker = ContentModificationTracker()
        tracker.mark_inbound_modified("test")
        assert tracker.requires_usage_recalculation() is True

    def test_requires_usage_recalculation_outbound(self) -> None:
        """Outbound modification should require recalculation."""
        tracker = ContentModificationTracker()
        tracker.mark_outbound_modified("test")
        assert tracker.requires_usage_recalculation() is True

    def test_requires_usage_recalculation_both(self) -> None:
        """Both modifications should require recalculation."""
        tracker = ContentModificationTracker()
        tracker.mark_inbound_modified("inbound_test")
        tracker.mark_outbound_modified("outbound_test")
        assert tracker.requires_usage_recalculation() is True

    def test_get_modification_summary(self) -> None:
        """Summary should contain all modification info."""
        tracker = ContentModificationTracker()
        tracker.mark_inbound_modified(
            "system_prompt",
            original_tokens=100,
            modified_tokens=150,
        )
        tracker.mark_outbound_modified(
            "think_removal",
            original_tokens=200,
            modified_tokens=180,
        )

        summary = tracker.get_modification_summary()

        assert summary["inbound_modified"] is True
        assert summary["outbound_modified"] is True
        assert "system_prompt" in summary["inbound_reasons"]
        assert "think_removal" in summary["outbound_reasons"]
        assert summary["inbound_token_delta"] == 50
        assert summary["outbound_token_delta"] == -20


class TestProcessingContextModificationTracking:
    """Test ProcessingContext integration with modification tracking."""

    def test_processing_context_has_tracker(self) -> None:
        """ProcessingContext should have a modification tracker."""
        context = ProcessingContext()
        assert context.modification_tracker is not None
        assert isinstance(context.modification_tracker, ContentModificationTracker)

    def test_mark_inbound_modified_convenience(self) -> None:
        """Convenience method should delegate to tracker."""
        context = ProcessingContext()
        context.mark_inbound_modified("test_reason")

        assert context.modification_tracker.inbound_modified is True
        assert (
            "test_reason" in context.modification_tracker.inbound_modification_reasons
        )

    def test_mark_outbound_modified_convenience(self) -> None:
        """Convenience method should delegate to tracker."""
        context = ProcessingContext()
        context.mark_outbound_modified("test_reason")

        assert context.modification_tracker.outbound_modified is True
        assert (
            "test_reason" in context.modification_tracker.outbound_modification_reasons
        )


class TestRequestContextModificationTracking:
    """Test RequestContext integration with modification tracking."""

    @pytest.fixture
    def context(self) -> RequestContext:
        """Create a basic request context."""
        return RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

    def test_ensure_processing_context_creates(self, context: RequestContext) -> None:
        """ensure_processing_context should create if missing."""
        # Initially no processing context
        context.processing_context = None

        processing = context.ensure_processing_context()

        assert processing is not None
        assert context.processing_context is processing

    def test_ensure_processing_context_returns_existing(
        self, context: RequestContext
    ) -> None:
        """ensure_processing_context should return existing."""
        existing = ProcessingContext()
        context.processing_context = existing

        result = context.ensure_processing_context()

        assert result is existing

    def test_get_modification_tracker(self, context: RequestContext) -> None:
        """get_modification_tracker should create context if needed."""
        context.processing_context = None

        tracker = context.get_modification_tracker()

        assert tracker is not None
        assert isinstance(tracker, ContentModificationTracker)
        assert context.processing_context is not None

    def test_mark_inbound_modified(self, context: RequestContext) -> None:
        """mark_inbound_modified should work through context."""
        context.mark_inbound_modified("test", original_tokens=100, modified_tokens=110)

        tracker = context.get_modification_tracker()
        assert tracker.inbound_modified is True
        assert tracker.inbound_original_tokens == 100
        assert tracker.inbound_modified_tokens == 110

    def test_mark_outbound_modified(self, context: RequestContext) -> None:
        """mark_outbound_modified should work through context."""
        context.mark_outbound_modified("test", original_tokens=200, modified_tokens=190)

        tracker = context.get_modification_tracker()
        assert tracker.outbound_modified is True
        assert tracker.outbound_original_tokens == 200
        assert tracker.outbound_modified_tokens == 190

    def test_requires_usage_recalculation_no_context(self) -> None:
        """requires_usage_recalculation should return False without context."""
        context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
            processing_context=None,
        )
        assert context.requires_usage_recalculation() is False

    def test_requires_usage_recalculation_with_mods(
        self, context: RequestContext
    ) -> None:
        """requires_usage_recalculation should return True with modifications."""
        context.mark_inbound_modified("test")
        assert context.requires_usage_recalculation() is True

    def test_with_processing_context_preserves_tracker(
        self, context: RequestContext
    ) -> None:
        """with_processing_context should preserve modification tracker."""
        context.mark_inbound_modified("original_reason")

        new_context = context.with_processing_context(extra="value")

        tracker = new_context.get_modification_tracker()
        assert tracker.inbound_modified is True
        assert "original_reason" in tracker.inbound_modification_reasons


class TestModificationTrackingScenarios:
    """Test real-world modification tracking scenarios."""

    def test_system_prompt_injection_scenario(self) -> None:
        """Test tracking system prompt injection."""
        context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        # Simulate system prompt injection
        original_tokens = 50
        with_system_prompt = 150  # System prompt adds 100 tokens

        context.mark_inbound_modified(
            reason="system_prompt_injection",
            original_tokens=original_tokens,
            modified_tokens=with_system_prompt,
        )

        tracker = context.get_modification_tracker()
        summary = tracker.get_modification_summary()

        assert summary["inbound_token_delta"] == 100
        assert context.requires_usage_recalculation() is True

    def test_think_tag_removal_scenario(self) -> None:
        """Test tracking think tag removal from response."""
        context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        # Simulate think tag removal
        with_think_tags = 500
        without_think_tags = 300  # Think tags contained 200 tokens

        context.mark_outbound_modified(
            reason="think_tag_removal",
            original_tokens=with_think_tags,
            modified_tokens=without_think_tags,
        )

        tracker = context.get_modification_tracker()
        summary = tracker.get_modification_summary()

        assert summary["outbound_token_delta"] == -200
        assert context.requires_usage_recalculation() is True

    def test_api_key_redaction_scenario(self) -> None:
        """Test tracking API key redaction from request."""
        context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        # Simulate API key redaction (minimal token change)
        context.mark_inbound_modified(
            reason="api_key_redaction",
            original_tokens=100,
            modified_tokens=98,
        )

        assert context.requires_usage_recalculation() is True

    def test_json_repair_scenario(self) -> None:
        """Test tracking JSON repair in response."""
        context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        # Simulate JSON repair (might slightly change token count)
        context.mark_outbound_modified(
            reason="json_repair",
            original_tokens=150,
            modified_tokens=152,
        )

        assert context.requires_usage_recalculation() is True

    def test_multiple_modifications_scenario(self) -> None:
        """Test multiple modifications on both paths."""
        context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
        )

        # Inbound modifications
        context.mark_inbound_modified("system_prompt_injection")
        context.mark_inbound_modified("tool_definition_expansion")

        # Outbound modifications
        context.mark_outbound_modified("think_tag_removal")
        context.mark_outbound_modified("content_filtering")

        tracker = context.get_modification_tracker()
        assert len(tracker.inbound_modification_reasons) == 2
        assert len(tracker.outbound_modification_reasons) == 2
        assert context.requires_usage_recalculation() is True
