"""Usage header injection for response adapters."""

from __future__ import annotations

from typing import Any


class UsageHeaderInjector:
    """Apply usage data as HTTP headers.

    Injects usage information into response headers for client consumption.
    Includes both basic token counts and extended fields when available.
    """

    def inject_headers(
        self, headers: dict[str, str], usage: dict[str, Any]
    ) -> dict[str, str]:
        """Add usage headers to response headers.

        Args:
            headers: Existing headers dictionary
            usage: Usage dictionary

        Returns:
            Headers dictionary with usage headers added
        """
        merged_headers: dict[str, str] = dict(headers or {})
        if usage is None:
            return merged_headers

        def _coerce_int(value: int | float | None) -> str:
            try:
                return str(int(value or 0))
            except Exception:
                return "0"

        def _coerce_float(value: float | None) -> str | None:
            if value is None:
                return None
            try:
                return str(float(value))
            except Exception:
                return None

        # Basic token counts (always included)
        merged_headers["x-usage-prompt-tokens"] = _coerce_int(
            usage.get("prompt_tokens")
        )
        merged_headers["x-usage-completion-tokens"] = _coerce_int(
            usage.get("completion_tokens")
        )
        merged_headers["x-usage-total-tokens"] = _coerce_int(usage.get("total_tokens"))

        # Extended: completion tokens details
        completion_details = usage.get("completion_tokens_details")
        if isinstance(completion_details, dict):
            reasoning_tokens = completion_details.get("reasoning_tokens")
            if reasoning_tokens is not None:
                merged_headers["x-usage-reasoning-tokens"] = _coerce_int(
                    reasoning_tokens
                )

        # Extended: prompt tokens details
        prompt_details = usage.get("prompt_tokens_details")
        if isinstance(prompt_details, dict):
            cached_tokens = prompt_details.get("cached_tokens")
            if cached_tokens is not None:
                merged_headers["x-usage-cached-tokens"] = _coerce_int(cached_tokens)
            audio_tokens = prompt_details.get("audio_tokens")
            if audio_tokens is not None:
                merged_headers["x-usage-audio-tokens"] = _coerce_int(audio_tokens)

        # Extended: cost
        cost = usage.get("cost")
        cost_str = _coerce_float(cost)
        if cost_str is not None:
            merged_headers["x-usage-cost"] = cost_str

        return merged_headers
