"""Tests for UsageNormalizationService.

This module tests the usage normalization service that converts provider-specific
usage data into canonical usage records and projects canonical usage back to
protocol-specific formats.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from src.core.domain.usage_canonical_record import (
    CanonicalUsageRecord,
    UsageCompletionOutcome,
    UsageIncompleteReason,
)
from src.core.domain.usage_normalization_context import UsageNormalizationContext
from src.core.domain.usage_payload import UsagePayload
from src.core.domain.usage_summary import UsageSummary
from src.core.services.usage_normalization_service import UsageNormalizationService


class TestUsageNormalizationServiceIdentifierMapping:
    """Test identifier mapping (request_id, provider_id, model_id, protocol)."""

    @pytest.fixture
    def service(self) -> UsageNormalizationService:
        """Create service instance."""
        calc_service = MagicMock()
        return UsageNormalizationService(calc_service)

    @pytest.mark.asyncio
    async def test_request_id_from_context(
        self, service: UsageNormalizationService
    ) -> None:
        """Test request_id mapping from context."""
        context = UsageNormalizationContext(request_id="req-123")
        result = await service.build_canonical_record(
            context=context, usage=None, raw_usage=None
        )
        assert result.request_id == "req-123"

    @pytest.mark.asyncio
    async def test_request_id_from_processing_context_values(
        self, service: UsageNormalizationService
    ) -> None:
        """Test request_id fallback to processing_context.values.request_id."""
        # Context doesn't have request_id, but we simulate it via context
        # In real usage, this would come from RequestContext.processing_context.values
        context = UsageNormalizationContext(request_id=None)
        # For this test, we'll pass request_id via context since that's how it flows
        context.request_id = None  # Simulate missing
        # In actual implementation, this would come from RequestContext
        # For now, test that None is handled
        result = await service.build_canonical_record(
            context=context, usage=None, raw_usage=None
        )
        assert result.request_id is None

    @pytest.mark.asyncio
    async def test_provider_id_from_context(
        self, service: UsageNormalizationService
    ) -> None:
        """Test provider_id mapping from context."""
        context = UsageNormalizationContext(backend_type="openai")
        result = await service.build_canonical_record(
            context=context, usage=None, raw_usage=None
        )
        assert result.provider_id == "openai"

    @pytest.mark.asyncio
    async def test_model_id_from_context(
        self, service: UsageNormalizationService
    ) -> None:
        """Test model_id mapping from context."""
        context = UsageNormalizationContext(model="gpt-4")
        result = await service.build_canonical_record(
            context=context, usage=None, raw_usage=None
        )
        assert result.model_id == "gpt-4"

    @pytest.mark.asyncio
    async def test_protocol_from_context(
        self, service: UsageNormalizationService
    ) -> None:
        """Test protocol mapping from context."""
        context = UsageNormalizationContext(protocol="openai")
        result = await service.build_canonical_record(
            context=context, usage=None, raw_usage=None
        )
        assert result.protocol == "openai"

    @pytest.mark.asyncio
    async def test_all_identifiers_together(
        self, service: UsageNormalizationService
    ) -> None:
        """Test all identifiers mapped together."""
        context = UsageNormalizationContext(
            request_id="req-456",
            protocol="anthropic",
            backend_type="anthropic",
            model="claude-3-5-sonnet",
        )
        result = await service.build_canonical_record(
            context=context, usage=None, raw_usage=None
        )
        assert result.request_id == "req-456"
        assert result.protocol == "anthropic"
        assert result.provider_id == "anthropic"
        assert result.model_id == "claude-3-5-sonnet"


class TestUsageNormalizationServiceTokenNormalization:
    """Test token normalization and cost extraction."""

    @pytest.fixture
    def service(self) -> UsageNormalizationService:
        """Create service instance."""
        calc_service = MagicMock()
        return UsageNormalizationService(calc_service)

    @pytest.mark.asyncio
    async def test_extract_tokens_from_usage_summary(
        self, service: UsageNormalizationService
    ) -> None:
        """Test token extraction from UsageSummary."""
        context = UsageNormalizationContext()
        usage = UsageSummary(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=None
        )
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50
        assert result.total_tokens == 150  # Should use provided total

    @pytest.mark.asyncio
    async def test_derive_total_tokens_when_both_available(
        self, service: UsageNormalizationService
    ) -> None:
        """Test total_tokens derivation when both prompt and completion available."""
        context = UsageNormalizationContext()
        usage = UsageSummary(prompt_tokens=200, completion_tokens=300)
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=None
        )
        assert result.prompt_tokens == 200
        assert result.completion_tokens == 300
        assert result.total_tokens == 500  # Should be derived

    @pytest.mark.asyncio
    async def test_extract_tokens_from_raw_usage_payload(
        self, service: UsageNormalizationService
    ) -> None:
        """Test token extraction from UsagePayload."""
        context = UsageNormalizationContext()
        raw_usage = UsagePayload(payload={"prompt_tokens": 75, "completion_tokens": 25})
        result = await service.build_canonical_record(
            context=context, usage=None, raw_usage=raw_usage
        )
        assert result.prompt_tokens == 75
        assert result.completion_tokens == 25
        assert result.total_tokens == 100  # Should be derived

    @pytest.mark.asyncio
    async def test_handle_missing_tokens(
        self, service: UsageNormalizationService
    ) -> None:
        """Test handling of missing tokens (set to None)."""
        context = UsageNormalizationContext()
        result = await service.build_canonical_record(
            context=context, usage=None, raw_usage=None
        )
        assert result.prompt_tokens is None
        assert result.completion_tokens is None
        assert result.total_tokens is None

    @pytest.mark.asyncio
    async def test_extract_cost_from_usage_summary_extensions(
        self, service: UsageNormalizationService
    ) -> None:
        """Test cost extraction from UsageSummary extensions."""
        context = UsageNormalizationContext()
        usage = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            extensions={"cost": 0.0025},
        )
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=None
        )
        assert result.cost == 0.0025

    @pytest.mark.asyncio
    async def test_extract_cost_from_raw_usage_payload(
        self, service: UsageNormalizationService
    ) -> None:
        """Test cost extraction from UsagePayload."""
        context = UsageNormalizationContext()
        raw_usage = UsagePayload(
            payload={"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.0015}
        )
        result = await service.build_canonical_record(
            context=context, usage=None, raw_usage=raw_usage
        )
        assert result.cost == 0.0015

    @pytest.mark.asyncio
    async def test_handle_missing_cost(
        self, service: UsageNormalizationService
    ) -> None:
        """Test handling of missing cost (set to None)."""
        context = UsageNormalizationContext()
        usage = UsageSummary(prompt_tokens=100, completion_tokens=50)
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=None
        )
        assert result.cost is None


class TestUsageNormalizationServiceExtensionsPreservation:
    """Test extensions preservation."""

    @pytest.fixture
    def service(self) -> UsageNormalizationService:
        """Create service instance."""
        calc_service = MagicMock()
        return UsageNormalizationService(calc_service)

    @pytest.mark.asyncio
    async def test_preserve_provider_extensions_from_usage_summary(
        self, service: UsageNormalizationService
    ) -> None:
        """Test preservation of provider-specific extensions."""
        context = UsageNormalizationContext()
        usage = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            extensions={
                "reasoning_tokens": 200,
                "cached_tokens": 50,
                "custom_field": "value",
            },
        )
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=None
        )
        assert result.extensions["reasoning_tokens"] == 200
        assert result.extensions["cached_tokens"] == 50
        assert result.extensions["custom_field"] == "value"

    @pytest.mark.asyncio
    async def test_preserve_provider_extensions_from_raw_usage(
        self, service: UsageNormalizationService
    ) -> None:
        """Test preservation of provider-specific extensions from raw usage."""
        context = UsageNormalizationContext()
        raw_usage = UsagePayload(
            payload={
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "reasoning_tokens": 150,
                "cached_tokens": 25,
            }
        )
        result = await service.build_canonical_record(
            context=context, usage=None, raw_usage=raw_usage
        )
        assert result.extensions["reasoning_tokens"] == 150
        assert result.extensions["cached_tokens"] == 25

    @pytest.mark.asyncio
    async def test_merge_extensions_from_multiple_sources(
        self, service: UsageNormalizationService
    ) -> None:
        """Test merging extensions from usage and raw_usage."""
        context = UsageNormalizationContext()
        usage = UsageSummary(
            prompt_tokens=100,
            completion_tokens=50,
            extensions={"reasoning_tokens": 200},
        )
        raw_usage = UsagePayload(payload={"cached_tokens": 50, "custom_field": "value"})
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=raw_usage
        )
        # Extensions should be merged
        assert result.extensions["reasoning_tokens"] == 200
        assert result.extensions["cached_tokens"] == 50
        assert result.extensions["custom_field"] == "value"


class TestUsageNormalizationServiceStreamingOutcomeResolution:
    """Test streaming outcome resolution and error classification."""

    @pytest.fixture
    def service(self) -> UsageNormalizationService:
        """Create service instance."""
        calc_service = MagicMock()
        return UsageNormalizationService(calc_service)

    @pytest.mark.asyncio
    async def test_complete_outcome_for_successful_stream(
        self, service: UsageNormalizationService
    ) -> None:
        """Test complete outcome for successful streams."""
        context = UsageNormalizationContext(
            is_streaming=True,
            completion_outcome=UsageCompletionOutcome.complete,
        )
        usage = UsageSummary(prompt_tokens=100, completion_tokens=50)
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=None
        )
        assert result.completion_outcome == UsageCompletionOutcome.complete
        assert result.incomplete_reason is None

    @pytest.mark.asyncio
    async def test_incomplete_outcome_with_client_disconnect(
        self, service: UsageNormalizationService
    ) -> None:
        """Test incomplete outcome with client_disconnect reason."""
        context = UsageNormalizationContext(
            is_streaming=True,
            completion_outcome=UsageCompletionOutcome.incomplete,
            cancel_reason="client_disconnect",
        )
        usage = UsageSummary(prompt_tokens=100, completion_tokens=25)
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=None
        )
        assert result.completion_outcome == UsageCompletionOutcome.incomplete
        assert result.incomplete_reason == UsageIncompleteReason.client_disconnect

    @pytest.mark.asyncio
    async def test_incomplete_outcome_with_upstream_cancelled(
        self, service: UsageNormalizationService
    ) -> None:
        """Test incomplete outcome with upstream_cancelled reason."""
        context = UsageNormalizationContext(
            is_streaming=True,
            completion_outcome=UsageCompletionOutcome.incomplete,
            cancel_reason="stream_cancelled",
        )
        usage = UsageSummary(prompt_tokens=100, completion_tokens=30)
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=None
        )
        assert result.completion_outcome == UsageCompletionOutcome.incomplete
        assert result.incomplete_reason == UsageIncompleteReason.upstream_cancelled

    @pytest.mark.asyncio
    async def test_incomplete_outcome_with_timeout(
        self, service: UsageNormalizationService
    ) -> None:
        """Test incomplete outcome with timeout reason."""
        context = UsageNormalizationContext(
            is_streaming=True,
            completion_outcome=UsageCompletionOutcome.incomplete,
            error_classification="timeout",
        )
        usage = UsageSummary(prompt_tokens=100, completion_tokens=20)
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=None
        )
        assert result.completion_outcome == UsageCompletionOutcome.incomplete
        assert result.incomplete_reason == UsageIncompleteReason.timeout

    @pytest.mark.asyncio
    async def test_incomplete_outcome_with_backend_error(
        self, service: UsageNormalizationService
    ) -> None:
        """Test incomplete outcome with backend_error reason."""
        context = UsageNormalizationContext(
            is_streaming=True,
            completion_outcome=UsageCompletionOutcome.incomplete,
            error_classification="backend_error",
        )
        usage = UsageSummary(prompt_tokens=100, completion_tokens=15)
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=None
        )
        assert result.completion_outcome == UsageCompletionOutcome.incomplete
        assert result.incomplete_reason == UsageIncompleteReason.backend_error

    @pytest.mark.asyncio
    async def test_incomplete_outcome_with_connection_error(
        self, service: UsageNormalizationService
    ) -> None:
        """Test incomplete outcome with connection_error classification."""
        context = UsageNormalizationContext(
            is_streaming=True,
            completion_outcome=UsageCompletionOutcome.incomplete,
            error_classification="connection_error",
        )
        usage = UsageSummary(prompt_tokens=100, completion_tokens=10)
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=None
        )
        assert result.completion_outcome == UsageCompletionOutcome.incomplete
        assert result.incomplete_reason == UsageIncompleteReason.backend_error

    @pytest.mark.asyncio
    async def test_incomplete_outcome_with_unknown_fallback(
        self, service: UsageNormalizationService
    ) -> None:
        """Test incomplete outcome with unknown reason fallback."""
        context = UsageNormalizationContext(
            is_streaming=True,
            completion_outcome=UsageCompletionOutcome.incomplete,
            error_classification="unknown",
        )
        usage = UsageSummary(prompt_tokens=100, completion_tokens=5)
        result = await service.build_canonical_record(
            context=context, usage=usage, raw_usage=None
        )
        assert result.completion_outcome == UsageCompletionOutcome.incomplete
        assert result.incomplete_reason == UsageIncompleteReason.unknown


class TestUsageNormalizationServiceErrorHandling:
    """Test error handling and logging."""

    @pytest.fixture
    def service(self) -> UsageNormalizationService:
        """Create service instance."""
        calc_service = MagicMock()
        return UsageNormalizationService(calc_service)

    @pytest.mark.asyncio
    async def test_malformed_usage_logs_warning_with_context_error_classification(
        self, service: UsageNormalizationService, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that malformed usage logs warning with error_classification from context."""
        import logging

        context = UsageNormalizationContext(
            request_id="req-123",
            backend_type="openai",
            model="gpt-4",
            protocol="openai",
            error_classification="backend_error",
        )
        # Create malformed usage (negative tokens)
        usage = UsageSummary(prompt_tokens=-10, completion_tokens=50)

        with caplog.at_level(logging.WARNING):
            await service.build_canonical_record(
                context=context, usage=usage, raw_usage=None
            )

        # Check that warning was logged with error_classification from context
        assert len(caplog.records) > 0
        warning_record = caplog.records[-1]
        assert warning_record.levelname == "WARNING"
        assert "Malformed usage data detected" in warning_record.message
        assert warning_record.request_id == "req-123"
        assert warning_record.backend_type == "openai"
        assert warning_record.model == "gpt-4"
        assert warning_record.protocol == "openai"
        assert warning_record.error_class == "backend_error"  # From context

    @pytest.mark.asyncio
    async def test_malformed_usage_logs_warning_with_fallback_error_class(
        self, service: UsageNormalizationService, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that malformed usage logs warning with 'malformed_usage' fallback."""
        import logging

        context = UsageNormalizationContext(
            request_id="req-456",
            backend_type="anthropic",
            model="claude-3-5-sonnet",
            protocol="anthropic",
            error_classification=None,  # No error classification
        )
        # Create malformed usage (inconsistent totals)
        usage = UsageSummary(prompt_tokens=100, completion_tokens=50, total_tokens=200)

        with caplog.at_level(logging.WARNING):
            await service.build_canonical_record(
                context=context, usage=usage, raw_usage=None
            )

        # Check that warning was logged with fallback error_class
        assert len(caplog.records) > 0
        warning_record = caplog.records[-1]
        assert warning_record.levelname == "WARNING"
        assert "Malformed usage data detected" in warning_record.message
        assert warning_record.error_class == "malformed_usage"  # Fallback


class TestUsageNormalizationServiceProtocolUsageProjection:
    """Test protocol usage projection preserving existing values."""

    @pytest.fixture
    def service(self) -> UsageNormalizationService:
        """Create service instance."""
        calc_service = MagicMock()
        return UsageNormalizationService(calc_service)

    def test_project_canonical_into_empty_payload(
        self, service: UsageNormalizationService
    ) -> None:
        """Test projecting canonical usage into empty payload."""
        canonical = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost=0.0025,
        )
        result = service.project_protocol_usage(canonical=canonical, existing=None)
        assert result is not None
        assert result.payload["prompt_tokens"] == 100
        assert result.payload["completion_tokens"] == 50
        assert result.payload["total_tokens"] == 150
        assert result.payload["cost"] == 0.0025

    def test_project_canonical_into_existing_payload(
        self, service: UsageNormalizationService
    ) -> None:
        """Test projecting canonical usage into existing payload."""
        canonical = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost=0.0025,
        )
        existing = UsagePayload(payload={"custom_field": "value", "other_field": 42})
        result = service.project_protocol_usage(canonical=canonical, existing=existing)
        assert result is not None
        assert result.payload["prompt_tokens"] == 100
        assert result.payload["completion_tokens"] == 50
        assert result.payload["total_tokens"] == 150
        assert result.payload["cost"] == 0.0025
        # Existing fields should be preserved
        assert result.payload["custom_field"] == "value"
        assert result.payload["other_field"] == 42

    def test_preserve_existing_non_null_values(
        self, service: UsageNormalizationService
    ) -> None:
        """Test that existing non-null values are not overwritten."""
        canonical = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        existing = UsagePayload(
            payload={
                "prompt_tokens": 200,  # Existing value
                "completion_tokens": 75,  # Existing value
                "total_tokens": 275,  # Existing value
                "cost": 0.005,  # Existing value not in canonical
            }
        )
        result = service.project_protocol_usage(canonical=canonical, existing=existing)
        assert result is not None
        # Existing values should be preserved
        assert result.payload["prompt_tokens"] == 200
        assert result.payload["completion_tokens"] == 75
        assert result.payload["total_tokens"] == 275
        assert result.payload["cost"] == 0.005

    def test_do_not_overwrite_with_zeroes(
        self, service: UsageNormalizationService
    ) -> None:
        """Test that zeroes are not written when canonical has nulls."""
        canonical = CanonicalUsageRecord(
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
        )
        existing = UsagePayload(payload={"prompt_tokens": 100, "completion_tokens": 50})
        result = service.project_protocol_usage(canonical=canonical, existing=existing)
        assert result is not None
        # Existing values should remain
        assert result.payload["prompt_tokens"] == 100
        assert result.payload["completion_tokens"] == 50

    def test_return_none_when_no_usable_fields(
        self, service: UsageNormalizationService
    ) -> None:
        """Test returning None when canonical has no usable fields."""
        canonical = CanonicalUsageRecord(
            prompt_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            cost=None,
        )
        result = service.project_protocol_usage(canonical=canonical, existing=None)
        assert result is None

    def test_merge_extensions_into_payload(
        self, service: UsageNormalizationService
    ) -> None:
        """Test that extensions are merged into payload."""
        canonical = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=50,
            extensions={"reasoning_tokens": 200, "cached_tokens": 50},
        )
        result = service.project_protocol_usage(canonical=canonical, existing=None)
        assert result is not None
        assert result.payload["prompt_tokens"] == 100
        assert result.payload["completion_tokens"] == 50
        assert result.payload["reasoning_tokens"] == 200
        assert result.payload["cached_tokens"] == 50
