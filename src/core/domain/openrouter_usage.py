"""OpenRouter-compatible usage data models.

This module provides Pydantic models that match the OpenRouter API usage format,
enabling accurate and comprehensive usage reporting to clients.

OpenRouter Usage Format Reference:
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

from pydantic import BaseModel, Field


class CompletionTokensDetails(BaseModel):
    """Details about completion token breakdown.

    Attributes:
        reasoning_tokens: Tokens used for reasoning/thinking (e.g., o1 models)
    """

    reasoning_tokens: int = Field(default=0, ge=0)

    model_config = {"extra": "allow"}


class PromptTokensDetails(BaseModel):
    """Details about prompt token breakdown.

    Attributes:
        cached_tokens: Tokens that were read from cache
        audio_tokens: Tokens from audio input (if applicable)
    """

    cached_tokens: int = Field(default=0, ge=0)
    audio_tokens: int = Field(default=0, ge=0)

    model_config = {"extra": "allow"}


class CostDetails(BaseModel):
    """Details about cost breakdown.

    Attributes:
        upstream_inference_cost: The actual cost charged by the upstream AI provider
            (only applies to BYOK - Bring Your Own Key requests)
    """

    upstream_inference_cost: float | None = Field(default=None, ge=0)

    model_config = {"extra": "allow"}


class OpenRouterUsage(BaseModel):
    """OpenRouter-compatible usage information.

    This model captures all usage information in OpenRouter API format,
    including basic token counts and extended details when available.

    Attributes:
        prompt_tokens: Number of tokens in the prompt (including images and tools)
        completion_tokens: Number of tokens generated in completion
        total_tokens: Sum of prompt_tokens and completion_tokens
        completion_tokens_details: Breakdown of completion tokens (reasoning, etc.)
        prompt_tokens_details: Breakdown of prompt tokens (cached, audio, etc.)
        cost: Total cost in credits (when available)
        cost_details: Breakdown of costs (upstream inference, etc.)
    """

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    completion_tokens_details: CompletionTokensDetails | None = None
    prompt_tokens_details: PromptTokensDetails | None = None
    cost: float | None = Field(default=None, ge=0)
    cost_details: CostDetails | None = None

    model_config = {"extra": "allow"}

    def model_post_init(self, __context: Any) -> None:
        """Ensure total_tokens is computed if not provided."""
        if self.total_tokens == 0 and (
            self.prompt_tokens > 0 or self.completion_tokens > 0
        ):
            object.__setattr__(
                self,
                "total_tokens",
                self.prompt_tokens + self.completion_tokens,
            )

    @classmethod
    def from_basic_usage(
        cls,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int | None = None,
    ) -> OpenRouterUsage:
        """Create usage from basic token counts.

        Args:
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            total_tokens: Total tokens (computed if not provided)

        Returns:
            OpenRouterUsage instance with basic fields populated
        """
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens

        return cls(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> OpenRouterUsage | None:
        """Parse usage from a dictionary, handling various formats.

        Supports:
        - OpenAI format: prompt_tokens, completion_tokens, total_tokens
        - Anthropic format: input_tokens, output_tokens
        - Gemini format: promptTokenCount, candidatesTokenCount, totalTokenCount
        - Extended OpenRouter format with details

        Args:
            data: Dictionary containing usage data

        Returns:
            OpenRouterUsage instance or None if data is None/empty
        """
        if not data:
            return None

        # Handle OpenAI/OpenRouter format
        prompt_tokens = data.get("prompt_tokens", 0)
        completion_tokens = data.get("completion_tokens", 0)
        total_tokens = data.get("total_tokens", 0)

        # Handle Anthropic format
        if "input_tokens" in data:
            prompt_tokens = data.get("input_tokens", prompt_tokens)
        if "output_tokens" in data:
            completion_tokens = data.get("output_tokens", completion_tokens)

        # Handle Gemini format
        if "promptTokenCount" in data:
            prompt_tokens = data.get("promptTokenCount", prompt_tokens)
        if "candidatesTokenCount" in data:
            completion_tokens = data.get("candidatesTokenCount", completion_tokens)
        if "totalTokenCount" in data:
            total_tokens = data.get("totalTokenCount", total_tokens)

        # Ensure total is computed
        if total_tokens == 0 and (prompt_tokens > 0 or completion_tokens > 0):
            total_tokens = prompt_tokens + completion_tokens

        # Parse extended details
        completion_details = None
        if data.get("completion_tokens_details"):
            details_data = data["completion_tokens_details"]
            if isinstance(details_data, dict):
                completion_details = CompletionTokensDetails(
                    reasoning_tokens=details_data.get("reasoning_tokens", 0)
                )

        prompt_details = None
        if data.get("prompt_tokens_details"):
            details_data = data["prompt_tokens_details"]
            if isinstance(details_data, dict):
                prompt_details = PromptTokensDetails(
                    cached_tokens=details_data.get("cached_tokens", 0),
                    audio_tokens=details_data.get("audio_tokens", 0),
                )

        # Handle cachedContent tokens (Gemini alternative format)
        if "cachedContentTokenCount" in data and prompt_details is None:
            prompt_details = PromptTokensDetails(
                cached_tokens=data.get("cachedContentTokenCount", 0)
            )
        elif "cachedContentTokenCount" in data and prompt_details is not None:
            prompt_details.cached_tokens = data.get(
                "cachedContentTokenCount", prompt_details.cached_tokens
            )

        # Parse cost details
        cost = data.get("cost")
        cost_details = None
        if data.get("cost_details"):
            cost_data = data["cost_details"]
            if isinstance(cost_data, dict):
                cost_details = CostDetails(
                    upstream_inference_cost=cost_data.get("upstream_inference_cost")
                )

        return cls(
            prompt_tokens=int(prompt_tokens) if prompt_tokens else 0,
            completion_tokens=int(completion_tokens) if completion_tokens else 0,
            total_tokens=int(total_tokens) if total_tokens else 0,
            completion_tokens_details=completion_details,
            prompt_tokens_details=prompt_details,
            cost=float(cost) if cost is not None else None,
            cost_details=cost_details,
        )

    def to_basic_dict(self) -> dict[str, int]:
        """Convert to basic usage dictionary (prompt_tokens, completion_tokens, total_tokens).

        Returns:
            Dictionary with basic usage fields only
        """
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

    def to_openrouter_dict(self) -> dict[str, Any]:
        """Convert to full OpenRouter format dictionary.

        Returns:
            Dictionary with all available usage fields in OpenRouter format
        """
        result: dict[str, Any] = {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

        if self.completion_tokens_details is not None:
            result["completion_tokens_details"] = (
                self.completion_tokens_details.model_dump(exclude_none=True)
            )

        if self.prompt_tokens_details is not None:
            result["prompt_tokens_details"] = self.prompt_tokens_details.model_dump(
                exclude_none=True
            )

        if self.cost is not None:
            result["cost"] = self.cost

        if self.cost_details is not None:
            result["cost_details"] = self.cost_details.model_dump(exclude_none=True)

        return result

    def with_recalculated_tokens(
        self,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> OpenRouterUsage:
        """Create a new instance with recalculated token counts.

        Preserves extended details (reasoning_tokens, cached_tokens, cost)
        while updating the base token counts.

        Args:
            prompt_tokens: New prompt token count (or None to keep existing)
            completion_tokens: New completion token count (or None to keep existing)

        Returns:
            New OpenRouterUsage with updated token counts
        """
        new_prompt = prompt_tokens if prompt_tokens is not None else self.prompt_tokens
        new_completion = (
            completion_tokens
            if completion_tokens is not None
            else self.completion_tokens
        )
        new_total = new_prompt + new_completion

        return OpenRouterUsage(
            prompt_tokens=new_prompt,
            completion_tokens=new_completion,
            total_tokens=new_total,
            completion_tokens_details=self.completion_tokens_details,
            prompt_tokens_details=self.prompt_tokens_details,
            cost=self.cost,
            cost_details=self.cost_details,
        )

    def merge_with(self, other: OpenRouterUsage | None) -> OpenRouterUsage:
        """Merge with another usage object, preferring non-zero/non-null values.

        Useful for combining usage from different sources (e.g., backend + proxy calculation).

        Args:
            other: Another usage object to merge with

        Returns:
            New OpenRouterUsage with merged values
        """
        if other is None:
            return self

        # Prefer non-zero values
        prompt = other.prompt_tokens if other.prompt_tokens > 0 else self.prompt_tokens
        completion = (
            other.completion_tokens
            if other.completion_tokens > 0
            else self.completion_tokens
        )
        total = prompt + completion

        # Prefer non-null extended details
        completion_details = (
            other.completion_tokens_details or self.completion_tokens_details
        )
        prompt_details = other.prompt_tokens_details or self.prompt_tokens_details
        cost = other.cost if other.cost is not None else self.cost
        cost_details = other.cost_details or self.cost_details

        return OpenRouterUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            completion_tokens_details=completion_details,
            prompt_tokens_details=prompt_details,
            cost=cost,
            cost_details=cost_details,
        )


def normalize_usage_to_openrouter(
    usage: dict[str, Any] | OpenRouterUsage | None,
) -> dict[str, Any] | None:
    """Normalize any usage format to OpenRouter format.

    This function accepts various usage formats and converts them to
    the standard OpenRouter dictionary format.

    Args:
        usage: Usage data in any supported format

    Returns:
        Dictionary in OpenRouter format or None
    """
    if usage is None:
        return None

    if isinstance(usage, OpenRouterUsage):
        return usage.to_openrouter_dict()

    if isinstance(usage, dict):
        parsed = OpenRouterUsage.from_dict(usage)
        if parsed is not None:
            return parsed.to_openrouter_dict()

    return None


def ensure_basic_usage_fields(usage: dict[str, Any] | None) -> dict[str, Any]:
    """Ensure basic usage fields are present with valid values.

    Args:
        usage: Existing usage dictionary or None

    Returns:
        Dictionary with at least prompt_tokens, completion_tokens, total_tokens
    """
    if usage is None:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    result = dict(usage)
    result.setdefault("prompt_tokens", 0)
    result.setdefault("completion_tokens", 0)

    # Ensure integers
    result["prompt_tokens"] = int(result["prompt_tokens"] or 0)
    result["completion_tokens"] = int(result["completion_tokens"] or 0)

    # Calculate total if missing or zero
    if result.get("total_tokens", 0) == 0:
        result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]
    else:
        result["total_tokens"] = int(result["total_tokens"])

    return result
