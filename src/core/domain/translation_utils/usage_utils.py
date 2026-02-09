from __future__ import annotations

from typing import Any


def normalize_usage_metadata(
    usage: dict[str, Any], source_format: str
) -> dict[str, Any]:
    """Normalize usage metadata from different API formats to a standard structure."""
    if source_format == "gemini":
        prompt_tokens = usage.get("promptTokenCount", 0)
        completion_tokens = usage.get("candidatesTokenCount", 0)
        total_tokens = usage.get("totalTokenCount", 0)
        reasoning_tokens = usage.get("reasoningTokenCount", 0)

        gemini_result: dict[str, Any] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

        if reasoning_tokens > 0:
            gemini_result["completion_tokens_details"] = {
                "reasoning_tokens": reasoning_tokens
            }

        return gemini_result

    if source_format == "anthropic":
        return {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0)
            + usage.get("output_tokens", 0),
        }
    if source_format in {"openai", "openai-responses"}:
        prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
        completion_tokens = usage.get(
            "completion_tokens", usage.get("output_tokens", 0)
        )
        total_tokens = usage.get("total_tokens")
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens

        result: dict[str, Any] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

        if "prompt_tokens_details" in usage:
            result["prompt_tokens_details"] = usage["prompt_tokens_details"]
        if "completion_tokens_details" in usage:
            result["completion_tokens_details"] = usage["completion_tokens_details"]

        return result

    return {
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }
