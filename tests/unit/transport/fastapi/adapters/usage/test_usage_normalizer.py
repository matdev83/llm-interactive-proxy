"""Tests for UsageNormalizer."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.core.domain.usage_summary import UsageSummary
from src.core.services.usage_calculation_service import UsageCalculationService
from src.core.transport.fastapi.adapters.usage.normalizer import UsageNormalizer


class TestUsageNormalizer:
    """Test UsageNormalizer implementation."""

    def test_normalization_adds_missing_fields_with_zero(self):
        """Test that normalization adds missing fields with 0."""
        sanitizer = UsageNormalizer()
        usage = {"prompt_tokens": 10}
        result = sanitizer.normalize(usage)
        assert result["prompt_tokens"] == 10
        assert result["completion_tokens"] == 0
        assert result["total_tokens"] == 10

    def test_normalization_converts_to_int(self):
        """Test that normalization converts values to int."""
        sanitizer = UsageNormalizer()
        usage = {
            "prompt_tokens": "10",
            "completion_tokens": 20.5,
            "total_tokens": "30",
        }
        result = sanitizer.normalize(usage)
        assert isinstance(result["prompt_tokens"], int)
        assert isinstance(result["completion_tokens"], int)
        assert isinstance(result["total_tokens"], int)
        assert result["prompt_tokens"] == 10
        assert result["completion_tokens"] == 20
        assert result["total_tokens"] == 30

    def test_merge_keeps_highest_values(self):
        """Test that merge keeps highest values."""
        sanitizer = UsageNormalizer()
        existing = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        new = {"prompt_tokens": 15, "completion_tokens": 18, "total_tokens": 25}
        result = sanitizer.merge_streaming_usage(existing, new)
        assert result["prompt_tokens"] == 15  # max(10, 15)
        assert result["completion_tokens"] == 20  # max(20, 18)
        # After normalization, new total becomes 33 (15+18), so max(30, 33) = 33
        assert result["total_tokens"] == 33

    def test_none_input_handling(self):
        """Test that None input returns dict with zeros."""
        sanitizer = UsageNormalizer()
        result = sanitizer.normalize(None)
        assert result == {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def test_usage_summary_handling(self):
        """Test that UsageSummary objects are handled correctly."""
        sanitizer = UsageNormalizer()
        usage_summary = UsageSummary(
            prompt_tokens=10, completion_tokens=20, total_tokens=30
        )
        result = sanitizer.normalize(usage_summary)
        assert result["prompt_tokens"] == 10
        assert result["completion_tokens"] == 20
        assert result["total_tokens"] == 30

    def test_merge_preserves_higher_cost(self):
        """Test that merge preserves higher cost values."""
        sanitizer = UsageNormalizer()
        existing = {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
            "cost": 0.01,
        }
        new = {
            "prompt_tokens": 15,
            "completion_tokens": 18,
            "total_tokens": 25,
            "cost": 0.02,
        }
        result = sanitizer.merge_streaming_usage(existing, new)
        assert result["cost"] == 0.02  # Higher cost preserved

    def test_merge_preserves_extended_details(self):
        """Test that merge preserves extended details."""
        sanitizer = UsageNormalizer()
        existing = {
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        }
        new = {
            "prompt_tokens": 15,
            "completion_tokens": 18,
            "total_tokens": 25,
            "completion_tokens_details": {"reasoning_tokens": 5},
        }
        result = sanitizer.merge_streaming_usage(existing, new)
        assert "completion_tokens_details" in result
        assert result["completion_tokens_details"]["reasoning_tokens"] == 5

    def test_merge_commutative_for_max(self):
        """Property test: merge is commutative for max operation."""
        sanitizer = UsageNormalizer()
        usage1 = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        usage2 = {"prompt_tokens": 15, "completion_tokens": 18, "total_tokens": 25}

        result1 = sanitizer.merge_streaming_usage(usage1, usage2)
        result2 = sanitizer.merge_streaming_usage(usage2, usage1)

        assert result1["prompt_tokens"] == result2["prompt_tokens"]
        assert result1["completion_tokens"] == result2["completion_tokens"]
        assert result1["total_tokens"] == result2["total_tokens"]

    def test_di_injection_works(self):
        """Test that DI injection works."""
        mock_service = MagicMock(spec=UsageCalculationService)
        sanitizer = UsageNormalizer(usage_service=mock_service)
        # Service is used internally when needed, but normalize should work without it
        result = sanitizer.normalize({"prompt_tokens": 10})
        assert result["prompt_tokens"] == 10

    def test_fallback_to_global_accessor(self):
        """Test that fallback to global accessor works."""
        sanitizer = UsageNormalizer()
        # Should not raise error even without explicit service
        result = sanitizer.normalize({"prompt_tokens": 10})
        assert result["prompt_tokens"] == 10

    def test_total_recalculated_if_less_than_sum(self):
        """Test that total is recalculated if less than sum of prompt + completion."""
        sanitizer = UsageNormalizer()
        usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 25}
        result = sanitizer.normalize(usage)
        assert result["total_tokens"] == 30  # Should be 10 + 20

    def test_merge_none_with_dict(self):
        """Test merging None with dict."""
        sanitizer = UsageNormalizer()
        existing = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        result = sanitizer.merge_streaming_usage(existing, None)
        assert result == existing

    def test_merge_dict_with_none(self):
        """Test merging dict with None."""
        sanitizer = UsageNormalizer()
        new = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        result = sanitizer.merge_streaming_usage(None, new)
        assert result == new

    def test_merge_both_none(self):
        """Test merging None with None."""
        sanitizer = UsageNormalizer()
        result = sanitizer.merge_streaming_usage(None, None)
        assert result == {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def test_responses_api_input_tokens_mapped_to_prompt_tokens(self):
        """Responses API uses input_tokens/output_tokens; normalizer must map them."""
        normalizer = UsageNormalizer()
        result = normalizer.normalize(
            {"input_tokens": 42, "output_tokens": 15, "total_tokens": 57}
        )
        assert result["prompt_tokens"] == 42
        assert result["completion_tokens"] == 15
        assert result["total_tokens"] == 57

    def test_responses_api_only_output_tokens_mapped(self):
        """If only output_tokens present (no prompt_tokens), it maps correctly."""
        normalizer = UsageNormalizer()
        result = normalizer.normalize({"output_tokens": 15, "total_tokens": 57})
        assert result["prompt_tokens"] == 0
        assert result["completion_tokens"] == 15
        assert result["total_tokens"] == 57

    def test_merge_preserves_responses_api_usage(self):
        """Merged streaming usage from Responses API preserves mapped token counts."""
        normalizer = UsageNormalizer()
        existing = {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
        new = {"input_tokens": 42, "output_tokens": 15, "total_tokens": 57}
        result = normalizer.merge_streaming_usage(existing, new)
        assert result["prompt_tokens"] == 42
        assert result["completion_tokens"] == 15
