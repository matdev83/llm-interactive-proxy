"""Usage header injection for response adapters."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.domain.usage_canonical_record import CanonicalUsageRecord
else:
    from src.core.domain.usage_canonical_record import CanonicalUsageRecord

logger = logging.getLogger(__name__)


class UsageHeaderInjector:
    """Apply usage data as HTTP headers.

    Injects usage information into response headers for client consumption.
    Includes both basic token counts and extended fields when available.
    """

    def inject_headers(
        self,
        headers: dict[str, str],
        usage: dict[str, Any],
        canonical_usage: CanonicalUsageRecord | None = None,
    ) -> dict[str, str]:
        """Add usage headers to response headers.

        Derives header values from canonical usage when available (Requirement 5.5),
        otherwise falls back to usage dictionary.

        Args:
            headers: Existing headers dictionary
            usage: Usage dictionary (fallback when canonical_usage is not available)
            canonical_usage: Optional canonical usage record (takes priority)

        Returns:
            Headers dictionary with usage headers added
        """
        merged_headers: dict[str, str] = dict(headers or {})

        # Priority: Use canonical usage when available (Requirement 5.5)
        if canonical_usage is not None:
            return self._inject_headers_from_canonical(merged_headers, canonical_usage)

        # Fallback to usage dict when canonical usage is not available
        if usage is None:
            return merged_headers

        def _coerce_int(value: int | float | None) -> str:
            try:
                return str(int(value or 0))
            except (ValueError, TypeError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to coerce value to int: %s, error: %s, returning '0'",
                        value,
                        e,
                        exc_info=True,
                    )
                return "0"

        def _coerce_float(value: float | None) -> str | None:
            if value is None:
                return None
            try:
                return str(float(value))
            except (ValueError, TypeError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to coerce value to float: %s, error: %s, returning None",
                        value,
                        e,
                        exc_info=True,
                    )
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

    def _inject_headers_from_canonical(
        self,
        headers: dict[str, str],
        canonical: CanonicalUsageRecord,
    ) -> dict[str, str]:
        """Inject headers from canonical usage record.

        Args:
            headers: Existing headers dictionary
            canonical: Canonical usage record

        Returns:
            Headers dictionary with usage headers added
        """

        merged_headers: dict[str, str] = dict(headers or {})

        def _coerce_int(value: int | float | None) -> str:
            try:
                return str(int(value or 0))
            except (ValueError, TypeError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to coerce value to int: %s, error: %s, returning '0'",
                        value,
                        e,
                        exc_info=True,
                    )
                return "0"

        def _coerce_float(value: float | None) -> str | None:
            if value is None:
                return None
            try:
                return str(float(value))
            except (ValueError, TypeError) as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to coerce value to float: %s, error: %s, returning None",
                        value,
                        e,
                        exc_info=True,
                    )
                return None

        # Basic token counts from canonical usage
        if canonical.prompt_tokens is not None:
            merged_headers["x-usage-prompt-tokens"] = _coerce_int(
                canonical.prompt_tokens
            )
        if canonical.completion_tokens is not None:
            merged_headers["x-usage-completion-tokens"] = _coerce_int(
                canonical.completion_tokens
            )
        if canonical.total_tokens is not None:
            merged_headers["x-usage-total-tokens"] = _coerce_int(canonical.total_tokens)

        # Extended fields from canonical extensions
        if canonical.extensions:
            # Completion tokens details (reasoning_tokens)
            completion_details = canonical.extensions.get("completion_tokens_details")
            if isinstance(completion_details, dict):
                reasoning_tokens = completion_details.get("reasoning_tokens")
                if reasoning_tokens is not None and isinstance(
                    reasoning_tokens, int | float
                ):
                    merged_headers["x-usage-reasoning-tokens"] = _coerce_int(
                        reasoning_tokens
                    )

            # Prompt tokens details (cached_tokens, audio_tokens)
            prompt_details = canonical.extensions.get("prompt_tokens_details")
            if isinstance(prompt_details, dict):
                cached_tokens = prompt_details.get("cached_tokens")
                if cached_tokens is not None and isinstance(cached_tokens, int | float):
                    merged_headers["x-usage-cached-tokens"] = _coerce_int(cached_tokens)
                audio_tokens = prompt_details.get("audio_tokens")
                if audio_tokens is not None and isinstance(audio_tokens, int | float):
                    merged_headers["x-usage-audio-tokens"] = _coerce_int(audio_tokens)

        # Cost from canonical usage
        if canonical.cost is not None:
            cost_str = _coerce_float(canonical.cost)
            if cost_str is not None:
                merged_headers["x-usage-cost"] = cost_str

        return merged_headers
