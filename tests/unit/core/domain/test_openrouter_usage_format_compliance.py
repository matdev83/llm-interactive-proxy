"""Tests for OpenRouter usage format compliance.

This module tests that usage information returned by the proxy conforms to
the OpenRouter API usage format specification.

OpenRouter Usage Format (from official docs):
{
  "usage": {
    "completion_tokens": 2,
    "completion_tokens_details": { "reasoning_tokens": 0 },
    "cost": 0.95,
    "cost_details": { "upstream_inference_cost": 19 },
    "prompt_tokens": 194,
    "prompt_tokens_details": { "cached_tokens": 0, "audio_tokens": 0 },
    "total_tokens": 196
  }
}
"""

from __future__ import annotations

from typing import Any

import pytest
from src.core.domain.openrouter_usage import (
    CompletionTokensDetails,
    CostDetails,
    OpenRouterUsage,
    PromptTokensDetails,
    ensure_basic_usage_fields,
    normalize_usage_to_openrouter,
)


class TestOpenRouterUsageBasicFields:
    """Test basic usage fields (prompt_tokens, completion_tokens, total_tokens)."""

    def test_basic_fields_present(self) -> None:
        """All basic fields should be present with default values."""
        usage = OpenRouterUsage()
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_basic_fields_with_values(self) -> None:
        """Basic fields should accept and store values."""
        usage = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_total_tokens_auto_calculated(self) -> None:
        """Total tokens should be auto-calculated if not provided."""
        usage = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
        )
        assert usage.total_tokens == 150

    def test_from_basic_usage_factory(self) -> None:
        """Test the from_basic_usage factory method."""
        usage = OpenRouterUsage.from_basic_usage(
            prompt_tokens=200,
            completion_tokens=100,
        )
        assert usage.prompt_tokens == 200
        assert usage.completion_tokens == 100
        assert usage.total_tokens == 300

    def test_to_basic_dict(self) -> None:
        """Test conversion to basic dict format."""
        usage = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )
        basic = usage.to_basic_dict()
        assert basic == {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }

    def test_negative_values_rejected(self) -> None:
        """Negative token values should be rejected."""
        with pytest.raises(ValueError):
            OpenRouterUsage(prompt_tokens=-1)

        with pytest.raises(ValueError):
            OpenRouterUsage(completion_tokens=-1)


class TestOpenRouterUsageExtendedFields:
    """Test extended usage fields (reasoning_tokens, cached_tokens, cost)."""

    def test_completion_tokens_details(self) -> None:
        """Test completion_tokens_details with reasoning_tokens."""
        details = CompletionTokensDetails(reasoning_tokens=50)
        usage = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=100,
            completion_tokens_details=details,
        )
        assert usage.completion_tokens_details is not None
        assert usage.completion_tokens_details.reasoning_tokens == 50

    def test_prompt_tokens_details(self) -> None:
        """Test prompt_tokens_details with cached_tokens and audio_tokens."""
        details = PromptTokensDetails(cached_tokens=30, audio_tokens=10)
        usage = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
            prompt_tokens_details=details,
        )
        assert usage.prompt_tokens_details is not None
        assert usage.prompt_tokens_details.cached_tokens == 30
        assert usage.prompt_tokens_details.audio_tokens == 10

    def test_cost_field(self) -> None:
        """Test cost field."""
        usage = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
            cost=0.95,
        )
        assert usage.cost == 0.95

    def test_cost_details(self) -> None:
        """Test cost_details with upstream_inference_cost."""
        cost_details = CostDetails(upstream_inference_cost=19.0)
        usage = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
            cost=0.95,
            cost_details=cost_details,
        )
        assert usage.cost_details is not None
        assert usage.cost_details.upstream_inference_cost == 19.0

    def test_to_openrouter_dict_with_all_fields(self) -> None:
        """Test conversion to full OpenRouter format dict."""
        usage = OpenRouterUsage(
            prompt_tokens=194,
            completion_tokens=2,
            total_tokens=196,
            completion_tokens_details=CompletionTokensDetails(reasoning_tokens=0),
            prompt_tokens_details=PromptTokensDetails(cached_tokens=0, audio_tokens=0),
            cost=0.95,
            cost_details=CostDetails(upstream_inference_cost=19.0),
        )
        result = usage.to_openrouter_dict()

        assert result["prompt_tokens"] == 194
        assert result["completion_tokens"] == 2
        assert result["total_tokens"] == 196
        assert result["completion_tokens_details"]["reasoning_tokens"] == 0
        assert result["prompt_tokens_details"]["cached_tokens"] == 0
        assert result["prompt_tokens_details"]["audio_tokens"] == 0
        assert result["cost"] == 0.95
        assert result["cost_details"]["upstream_inference_cost"] == 19.0


class TestOpenRouterUsageFromDict:
    """Test parsing usage from various dictionary formats."""

    def test_from_openai_format(self) -> None:
        """Test parsing OpenAI-style usage dict."""
        data = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        }
        usage = OpenRouterUsage.from_dict(data)
        assert usage is not None
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_from_anthropic_format(self) -> None:
        """Test parsing Anthropic-style usage dict."""
        data = {
            "input_tokens": 100,
            "output_tokens": 50,
        }
        usage = OpenRouterUsage.from_dict(data)
        assert usage is not None
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_from_gemini_format(self) -> None:
        """Test parsing Gemini-style usage dict."""
        data = {
            "promptTokenCount": 100,
            "candidatesTokenCount": 50,
            "totalTokenCount": 150,
        }
        usage = OpenRouterUsage.from_dict(data)
        assert usage is not None
        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_from_gemini_with_cached_tokens(self) -> None:
        """Test parsing Gemini format with cachedContentTokenCount."""
        data = {
            "promptTokenCount": 100,
            "candidatesTokenCount": 50,
            "totalTokenCount": 150,
            "cachedContentTokenCount": 20,
        }
        usage = OpenRouterUsage.from_dict(data)
        assert usage is not None
        assert usage.prompt_tokens_details is not None
        assert usage.prompt_tokens_details.cached_tokens == 20

    def test_from_openrouter_extended_format(self) -> None:
        """Test parsing full OpenRouter extended format."""
        data = {
            "prompt_tokens": 194,
            "completion_tokens": 2,
            "total_tokens": 196,
            "completion_tokens_details": {"reasoning_tokens": 10},
            "prompt_tokens_details": {"cached_tokens": 5, "audio_tokens": 3},
            "cost": 0.95,
            "cost_details": {"upstream_inference_cost": 19},
        }
        usage = OpenRouterUsage.from_dict(data)
        assert usage is not None
        assert usage.prompt_tokens == 194
        assert usage.completion_tokens == 2
        assert usage.total_tokens == 196
        assert usage.completion_tokens_details is not None
        assert usage.completion_tokens_details.reasoning_tokens == 10
        assert usage.prompt_tokens_details is not None
        assert usage.prompt_tokens_details.cached_tokens == 5
        assert usage.prompt_tokens_details.audio_tokens == 3
        assert usage.cost == 0.95
        assert usage.cost_details is not None
        assert usage.cost_details.upstream_inference_cost == 19

    def test_from_none_returns_none(self) -> None:
        """Parsing None should return None."""
        assert OpenRouterUsage.from_dict(None) is None

    def test_from_empty_dict_returns_zero_usage(self) -> None:
        """Parsing empty dict should return None."""
        assert OpenRouterUsage.from_dict({}) is None


class TestOpenRouterUsageRecalculation:
    """Test token recalculation functionality."""

    def test_with_recalculated_tokens_prompt_only(self) -> None:
        """Recalculating only prompt tokens should preserve other values."""
        original = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            completion_tokens_details=CompletionTokensDetails(reasoning_tokens=10),
            cost=0.95,
        )
        updated = original.with_recalculated_tokens(prompt_tokens=200)

        assert updated.prompt_tokens == 200
        assert updated.completion_tokens == 50
        assert updated.total_tokens == 250
        # Extended fields preserved
        assert updated.completion_tokens_details is not None
        assert updated.completion_tokens_details.reasoning_tokens == 10
        assert updated.cost == 0.95

    def test_with_recalculated_tokens_completion_only(self) -> None:
        """Recalculating only completion tokens should preserve other values."""
        original = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            prompt_tokens_details=PromptTokensDetails(cached_tokens=20),
        )
        updated = original.with_recalculated_tokens(completion_tokens=100)

        assert updated.prompt_tokens == 100
        assert updated.completion_tokens == 100
        assert updated.total_tokens == 200
        # Extended fields preserved
        assert updated.prompt_tokens_details is not None
        assert updated.prompt_tokens_details.cached_tokens == 20

    def test_with_recalculated_tokens_both(self) -> None:
        """Recalculating both should update total correctly."""
        original = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
        )
        updated = original.with_recalculated_tokens(
            prompt_tokens=200,
            completion_tokens=100,
        )

        assert updated.prompt_tokens == 200
        assert updated.completion_tokens == 100
        assert updated.total_tokens == 300

    def test_with_recalculated_tokens_none_preserves(self) -> None:
        """Passing None should preserve existing values."""
        original = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
        )
        updated = original.with_recalculated_tokens(
            prompt_tokens=None,
            completion_tokens=None,
        )

        assert updated.prompt_tokens == 100
        assert updated.completion_tokens == 50


class TestOpenRouterUsageMerge:
    """Test usage merging functionality."""

    def test_merge_prefers_nonzero(self) -> None:
        """Merge should prefer non-zero values."""
        base = OpenRouterUsage(
            prompt_tokens=0,
            completion_tokens=50,
        )
        other = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=0,
        )
        merged = base.merge_with(other)

        assert merged.prompt_tokens == 100
        assert merged.completion_tokens == 50

    def test_merge_prefers_other_extended(self) -> None:
        """Merge should prefer other's extended fields when present."""
        base = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
        )
        other = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
            completion_tokens_details=CompletionTokensDetails(reasoning_tokens=10),
        )
        merged = base.merge_with(other)

        assert merged.completion_tokens_details is not None
        assert merged.completion_tokens_details.reasoning_tokens == 10

    def test_merge_with_none(self) -> None:
        """Merge with None should return original."""
        base = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
        )
        merged = base.merge_with(None)

        assert merged.prompt_tokens == 100
        assert merged.completion_tokens == 50


class TestNormalizeUsageToOpenRouter:
    """Test the normalize_usage_to_openrouter helper function."""

    def test_normalize_dict(self) -> None:
        """Normalizing a dict should return OpenRouter format."""
        data: dict[str, Any] = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
        }
        result = normalize_usage_to_openrouter(data)
        assert result is not None
        assert result["prompt_tokens"] == 100
        assert result["completion_tokens"] == 50
        assert result["total_tokens"] == 150

    def test_normalize_openrouter_usage(self) -> None:
        """Normalizing an OpenRouterUsage should return dict."""
        usage = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=50,
        )
        result = normalize_usage_to_openrouter(usage)
        assert result is not None
        assert result["prompt_tokens"] == 100
        assert result["completion_tokens"] == 50

    def test_normalize_none(self) -> None:
        """Normalizing None should return None."""
        assert normalize_usage_to_openrouter(None) is None


class TestEnsureBasicUsageFields:
    """Test the ensure_basic_usage_fields helper function."""

    def test_ensure_with_none(self) -> None:
        """Should return zero-valued dict for None input."""
        result = ensure_basic_usage_fields(None)
        assert result["prompt_tokens"] == 0
        assert result["completion_tokens"] == 0
        assert result["total_tokens"] == 0

    def test_ensure_fills_missing(self) -> None:
        """Should fill in missing fields."""
        data: dict[str, Any] = {"prompt_tokens": 100}
        result = ensure_basic_usage_fields(data)
        assert result["prompt_tokens"] == 100
        assert result["completion_tokens"] == 0
        assert result["total_tokens"] == 100

    def test_ensure_calculates_total(self) -> None:
        """Should calculate total if zero."""
        data: dict[str, Any] = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 0,
        }
        result = ensure_basic_usage_fields(data)
        assert result["total_tokens"] == 150

    def test_ensure_preserves_extended(self) -> None:
        """Should preserve extended fields."""
        data: dict[str, Any] = {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "completion_tokens_details": {"reasoning_tokens": 10},
        }
        result = ensure_basic_usage_fields(data)
        assert "completion_tokens_details" in result
        assert result["completion_tokens_details"]["reasoning_tokens"] == 10


class TestOpenRouterUsageStreamingScenarios:
    """Test usage handling in streaming scenarios."""

    def test_streaming_final_chunk_format(self) -> None:
        """Final streaming chunk should have correct usage format."""
        # Simulate final chunk usage data
        final_chunk_usage = {
            "prompt_tokens": 194,
            "completion_tokens": 2,
            "total_tokens": 196,
        }
        usage = OpenRouterUsage.from_dict(final_chunk_usage)
        assert usage is not None

        # Convert back to dict for response
        result = usage.to_openrouter_dict()
        assert result["prompt_tokens"] == 194
        assert result["completion_tokens"] == 2
        assert result["total_tokens"] == 196

    def test_streaming_with_accumulated_content(self) -> None:
        """Usage should reflect accumulated content in streaming."""
        # In streaming, completion_tokens may need recalculation
        original = OpenRouterUsage(
            prompt_tokens=100,
            completion_tokens=10,  # Initial estimate
        )
        # After accumulation, we might recalculate
        updated = original.with_recalculated_tokens(completion_tokens=50)

        assert updated.completion_tokens == 50
        assert updated.total_tokens == 150


class TestOpenRouterUsageToolCallScenarios:
    """Test usage handling with tool calls."""

    def test_tool_call_preserves_usage(self) -> None:
        """Tool calls should not lose usage information."""
        usage = OpenRouterUsage(
            prompt_tokens=500,  # Higher due to tool definitions
            completion_tokens=100,
            completion_tokens_details=CompletionTokensDetails(reasoning_tokens=20),
        )
        result = usage.to_openrouter_dict()

        assert result["prompt_tokens"] == 500
        assert result["completion_tokens"] == 100
        assert result["completion_tokens_details"]["reasoning_tokens"] == 20

    def test_tool_result_adds_to_prompt(self) -> None:
        """Tool results should increase prompt token count."""
        # Initial request usage
        initial = OpenRouterUsage(
            prompt_tokens=200,
            completion_tokens=50,
        )
        # After tool result added to messages
        with_tool_result = initial.with_recalculated_tokens(prompt_tokens=300)

        assert with_tool_result.prompt_tokens == 300
        assert with_tool_result.completion_tokens == 50
        assert with_tool_result.total_tokens == 350
