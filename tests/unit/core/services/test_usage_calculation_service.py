"""Tests for UsageCalculationService.

This module tests the proxy-aware usage calculation service that handles:
1. Token calculation when backends don't provide usage
2. Recalculation when proxy modifications occur
3. Preservation of extended usage fields
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from src.core.domain.request_context import (
    ContentModificationTracker,
    ProcessingContext,
    RequestContext,
)
from src.core.services.usage_calculation_service import (
    UsageCalculationService,
    get_usage_calculation_service,
)


class TestUsageCalculationServiceBasics:
    """Test basic usage calculation functionality."""

    @pytest.fixture
    def service(self) -> UsageCalculationService:
        return UsageCalculationService()

    def test_calculate_prompt_tokens_simple(
        self, service: UsageCalculationService
    ) -> None:
        """Calculate prompt tokens from simple messages."""
        messages = [
            {"role": "user", "content": "Hello, world!"},
        ]
        tokens = service.calculate_prompt_tokens(messages)
        assert tokens > 0

    def test_calculate_prompt_tokens_multiple_messages(
        self, service: UsageCalculationService
    ) -> None:
        """Calculate prompt tokens from multiple messages."""
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is 2+2?"},
            {"role": "assistant", "content": "4"},
            {"role": "user", "content": "Thanks!"},
        ]
        tokens = service.calculate_prompt_tokens(messages)
        assert tokens > 10  # Multiple messages should have more tokens

    def test_calculate_prompt_tokens_empty_messages(
        self, service: UsageCalculationService
    ) -> None:
        """Empty messages should return 0 tokens."""
        tokens = service.calculate_prompt_tokens([])
        assert tokens == 0

    def test_calculate_completion_tokens_string(
        self, service: UsageCalculationService
    ) -> None:
        """Calculate completion tokens from string content."""
        content = "This is a test response with some content."
        tokens = service.calculate_completion_tokens(content)
        assert tokens > 0

    def test_calculate_completion_tokens_openai_dict(
        self, service: UsageCalculationService
    ) -> None:
        """Calculate completion tokens from OpenAI-style response dict."""
        content = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "The answer is 42.",
                    }
                }
            ]
        }
        tokens = service.calculate_completion_tokens(content)
        assert tokens > 0

    def test_calculate_completion_tokens_streaming_delta(
        self, service: UsageCalculationService
    ) -> None:
        """Calculate completion tokens from streaming delta dict."""
        content = {
            "choices": [
                {
                    "delta": {
                        "content": "Hello there!",
                    }
                }
            ]
        }
        tokens = service.calculate_completion_tokens(content)
        assert tokens > 0


class TestUsageCalculationWithModifications:
    """Test usage calculation with modification tracking."""

    @pytest.fixture
    def service(self) -> UsageCalculationService:
        return UsageCalculationService()

    @pytest.fixture
    def tracker_with_inbound_mod(self) -> ContentModificationTracker:
        """Create tracker with inbound modification."""
        tracker = ContentModificationTracker()
        tracker.mark_inbound_modified(
            reason="system_prompt_injection",
            original_tokens=100,
            modified_tokens=150,
        )
        return tracker

    @pytest.fixture
    def tracker_with_outbound_mod(self) -> ContentModificationTracker:
        """Create tracker with outbound modification."""
        tracker = ContentModificationTracker()
        tracker.mark_outbound_modified(
            reason="think_tag_processing",
            original_tokens=200,
            modified_tokens=180,
        )
        return tracker

    def test_should_recalculate_no_usage(
        self, service: UsageCalculationService
    ) -> None:
        """Should recalculate when no usage provided."""
        assert service.should_recalculate_usage(None, None) is True

    def test_should_recalculate_zero_usage(
        self, service: UsageCalculationService
    ) -> None:
        """Should recalculate when usage has zeros."""
        usage: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        assert service.should_recalculate_usage(usage, None) is True

    def test_should_recalculate_with_inbound_modification(
        self,
        service: UsageCalculationService,
        tracker_with_inbound_mod: ContentModificationTracker,
    ) -> None:
        """Should recalculate when inbound modification occurred."""
        usage: dict[str, Any] = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        assert service.should_recalculate_usage(usage, tracker_with_inbound_mod) is True

    def test_should_recalculate_with_outbound_modification(
        self,
        service: UsageCalculationService,
        tracker_with_outbound_mod: ContentModificationTracker,
    ) -> None:
        """Should recalculate when outbound modification occurred."""
        usage: dict[str, Any] = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        assert (
            service.should_recalculate_usage(usage, tracker_with_outbound_mod) is True
        )

    def test_should_not_recalculate_valid_usage_no_mods(
        self, service: UsageCalculationService
    ) -> None:
        """Should not recalculate when valid usage and no modifications."""
        usage: dict[str, Any] = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        assert service.should_recalculate_usage(usage, None) is False

    def test_recalculate_uses_tracker_tokens(
        self,
        service: UsageCalculationService,
        tracker_with_inbound_mod: ContentModificationTracker,
    ) -> None:
        """Recalculation should use tokens from tracker when available."""
        backend_usage: dict[str, Any] = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        result = service.recalculate_usage(
            backend_usage=backend_usage,
            modification_tracker=tracker_with_inbound_mod,
        )
        # Should use the modified_tokens from tracker
        assert result.prompt_tokens == 150  # From tracker.inbound_modified_tokens


class TestUsageCalculationPreservesExtended:
    """Test that extended usage fields are preserved."""

    @pytest.fixture
    def service(self) -> UsageCalculationService:
        return UsageCalculationService()

    @pytest.fixture
    def backend_usage_with_extended(self) -> dict[str, Any]:
        """Create backend usage with extended fields."""
        return {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "completion_tokens_details": {"reasoning_tokens": 20},
            "prompt_tokens_details": {"cached_tokens": 10},
            "cost": 0.95,
            "cost_details": {"upstream_inference_cost": 19},
        }

    def test_recalculate_preserves_reasoning_tokens(
        self,
        service: UsageCalculationService,
        backend_usage_with_extended: dict[str, Any],
    ) -> None:
        """Recalculation should preserve reasoning_tokens."""
        tracker = ContentModificationTracker()
        tracker.mark_outbound_modified("content_rewrite")

        result = service.recalculate_usage(
            backend_usage=backend_usage_with_extended,
            modification_tracker=tracker,
            response_content="Some modified content here.",
            model="gpt-4",
        )

        # Extended fields should be preserved
        result_dict = result.to_openrouter_dict()
        assert "completion_tokens_details" in result_dict
        assert result_dict["completion_tokens_details"]["reasoning_tokens"] == 20

    def test_recalculate_preserves_cached_tokens(
        self,
        service: UsageCalculationService,
        backend_usage_with_extended: dict[str, Any],
    ) -> None:
        """Recalculation should preserve cached_tokens."""
        tracker = ContentModificationTracker()
        tracker.mark_inbound_modified("api_key_redaction")

        result = service.recalculate_usage(
            backend_usage=backend_usage_with_extended,
            modification_tracker=tracker,
            messages=[{"role": "user", "content": "Test message"}],
            model="gpt-4",
        )

        result_dict = result.to_openrouter_dict()
        assert "prompt_tokens_details" in result_dict
        assert result_dict["prompt_tokens_details"]["cached_tokens"] == 10

    def test_recalculate_preserves_cost(
        self,
        service: UsageCalculationService,
        backend_usage_with_extended: dict[str, Any],
    ) -> None:
        """Recalculation should preserve cost information."""
        result = service.recalculate_usage(
            backend_usage=backend_usage_with_extended,
            modification_tracker=None,
        )

        result_dict = result.to_openrouter_dict()
        assert result_dict["cost"] == 0.95
        assert result_dict["cost_details"]["upstream_inference_cost"] == 19


class TestUsageCalculationWithContext:
    """Test usage calculation with RequestContext."""

    @pytest.fixture
    def service(self) -> UsageCalculationService:
        return UsageCalculationService()

    @pytest.fixture
    def context_with_modifications(self) -> RequestContext:
        """Create request context with modifications."""
        processing = ProcessingContext()
        processing.mark_outbound_modified("json_repair", modified_tokens=100)

        return RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
            processing_context=processing,
        )

    def test_ensure_usage_with_context(
        self,
        service: UsageCalculationService,
        context_with_modifications: RequestContext,
    ) -> None:
        """ensure_usage should use context's modification tracker."""
        backend_usage: dict[str, Any] = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        result = service.ensure_usage(
            backend_usage=backend_usage,
            context=context_with_modifications,
            response_content="Test content",
            model="gpt-4",
        )

        # Should return valid usage
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 100  # Recalculated from modification tracker
        assert result.total_tokens == 200

    def test_ensure_usage_without_context(
        self, service: UsageCalculationService
    ) -> None:
        """ensure_usage should work without context."""
        backend_usage: dict[str, Any] = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        result = service.ensure_usage(
            backend_usage=backend_usage,
            context=None,
        )

        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50
        assert result.total_tokens == 150



class TestGlobalServiceInstance:
    """Test the global service instance."""

    def test_get_usage_calculation_service_returns_instance(self) -> None:
        """get_usage_calculation_service should return a service instance."""
        service = get_usage_calculation_service()
        assert isinstance(service, UsageCalculationService)

    def test_get_usage_calculation_service_returns_same_instance(self) -> None:
        """get_usage_calculation_service should return the same instance."""
        service1 = get_usage_calculation_service()
        service2 = get_usage_calculation_service()
        assert service1 is service2


class TestStreamingUsageMerge:
    """Test streaming usage merge functionality."""

    @pytest.fixture
    def service(self) -> UsageCalculationService:
        return UsageCalculationService()

    def test_merge_streaming_usage_basic(
        self, service: UsageCalculationService
    ) -> None:
        """Basic streaming usage merge."""
        accumulated = "This is the accumulated streaming content."
        final_usage: dict[str, Any] = {
            "prompt_tokens": 50,
            "completion_tokens": 10,
            "total_tokens": 60,
        }
        result = service.merge_streaming_usage(
            accumulated_content=accumulated,
            final_chunk_usage=final_usage,
        )

        assert result.prompt_tokens == 50
        assert result.completion_tokens == 10

    def test_merge_streaming_usage_with_modifications(
        self, service: UsageCalculationService
    ) -> None:
        """Streaming usage should recalculate on modifications."""
        accumulated = "Modified content after think tag removal."

        processing = ProcessingContext()
        processing.mark_outbound_modified("think_tag_removal")

        context = RequestContext(
            headers={},
            cookies={},
            state=MagicMock(),
            app_state=MagicMock(),
            processing_context=processing,
        )

        final_usage: dict[str, Any] = {
            "prompt_tokens": 50,
            "completion_tokens": 100,  # Original before modification
            "total_tokens": 150,
        }

        result = service.merge_streaming_usage(
            accumulated_content=accumulated,
            final_chunk_usage=final_usage,
            context=context,
            model="gpt-4",
        )

        # Completion tokens should be recalculated from accumulated content
        assert result.completion_tokens > 0
        # Prompt tokens preserved from backend
        assert result.prompt_tokens == 50

    def test_merge_streaming_usage_no_final_chunk(
        self, service: UsageCalculationService
    ) -> None:
        """Should calculate from accumulated content when no final chunk usage."""
        accumulated = "Some content without usage data."
        result = service.merge_streaming_usage(
            accumulated_content=accumulated,
            final_chunk_usage=None,
        )

        assert result.completion_tokens > 0
        assert result.total_tokens == result.completion_tokens

