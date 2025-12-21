"""Tests for UsageHeaderInjector."""

from __future__ import annotations

from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.transport.fastapi.adapters.usage.header_injector import (
    UsageHeaderInjector,
)


class TestUsageHeaderInjector:
    """Test UsageHeaderInjector implementation."""

    def test_inject_headers_from_canonical_usage(self) -> None:
        """Test that headers are derived from canonical usage (Requirement 5.5)."""
        injector = UsageHeaderInjector()

        canonical_usage = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            cost=0.05,
        )

        result = injector.inject_headers({}, {}, canonical_usage=canonical_usage)

        assert result["x-usage-prompt-tokens"] == "100"
        assert result["x-usage-completion-tokens"] == "200"
        assert result["x-usage-total-tokens"] == "300"
        assert result["x-usage-cost"] == "0.05"

    def test_inject_headers_from_canonical_with_extensions(self) -> None:
        """Test that extended fields are extracted from canonical extensions."""
        injector = UsageHeaderInjector()

        canonical_usage = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
            extensions={
                "completion_tokens_details": {"reasoning_tokens": 50},
                "prompt_tokens_details": {"cached_tokens": 25, "audio_tokens": 10},
            },
        )

        result = injector.inject_headers({}, {}, canonical_usage=canonical_usage)

        assert result["x-usage-prompt-tokens"] == "100"
        assert result["x-usage-completion-tokens"] == "200"
        assert result["x-usage-total-tokens"] == "300"
        assert result["x-usage-reasoning-tokens"] == "50"
        assert result["x-usage-cached-tokens"] == "25"
        assert result["x-usage-audio-tokens"] == "10"

    def test_inject_headers_falls_back_to_usage_dict(self) -> None:
        """Test that headers fall back to usage dict when canonical usage is not available."""
        injector = UsageHeaderInjector()

        usage_dict = {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        }

        result = injector.inject_headers({}, usage_dict)

        assert result["x-usage-prompt-tokens"] == "10"
        assert result["x-usage-completion-tokens"] == "20"
        assert result["x-usage-total-tokens"] == "30"

    def test_inject_headers_canonical_null_values_not_overwritten(self) -> None:
        """Test that null values in canonical usage don't overwrite existing headers."""
        injector = UsageHeaderInjector()

        canonical_usage = CanonicalUsageRecord(
            prompt_tokens=None,  # Null value
            completion_tokens=200,
            total_tokens=300,
        )

        # Existing headers with prompt tokens
        existing_headers = {"x-usage-prompt-tokens": "50"}

        result = injector.inject_headers(
            existing_headers, {}, canonical_usage=canonical_usage
        )

        # Null prompt_tokens should not overwrite existing header
        # Existing headers are preserved, so prompt_tokens header remains
        assert result["x-usage-completion-tokens"] == "200"
        assert result["x-usage-total-tokens"] == "300"
        # Prompt tokens header is preserved from existing headers since canonical has null
        assert result["x-usage-prompt-tokens"] == "50"

    def test_inject_headers_preserves_existing_headers(self) -> None:
        """Test that existing headers are preserved."""
        injector = UsageHeaderInjector()

        canonical_usage = CanonicalUsageRecord(
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
        )

        existing_headers = {"x-custom-header": "value"}

        result = injector.inject_headers(
            existing_headers, {}, canonical_usage=canonical_usage
        )

        assert result["x-custom-header"] == "value"
        assert result["x-usage-prompt-tokens"] == "100"

    def test_inject_headers_handles_none_usage_dict(self) -> None:
        """Test that None usage dict is handled gracefully."""
        injector = UsageHeaderInjector()

        result = injector.inject_headers({}, None)

        # Should return headers without usage headers
        assert isinstance(result, dict)
        assert "x-usage-prompt-tokens" not in result
