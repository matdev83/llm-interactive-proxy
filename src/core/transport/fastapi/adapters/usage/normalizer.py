"""Usage normalization for response adapters."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.services.usage_calculation_service import UsageCalculationService

logger = logging.getLogger(__name__)


class UsageNormalizer:
    """Normalize usage dictionaries to standard format.

    Ensures standard fields are present as integers and provides
    merging logic that keeps highest values for streaming usage.
    """

    def __init__(
        self,
        usage_service: UsageCalculationService | None = None,
    ) -> None:
        """Initialize usage normalizer.

        Args:
            usage_service: Optional UsageCalculationService instance.
                          If not provided, falls back to global accessor.
        """
        self._usage_service = usage_service

    def normalize(self, usage: dict[str, Any] | None) -> dict[str, int]:
        """Normalize usage to standard format.

        Args:
            usage: Usage dictionary or None

        Returns:
            Normalized usage with standard fields as integers
        """
        if usage is None:
            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

        # Handle UsageSummary objects
        from src.core.domain.usage_summary import UsageSummary

        if isinstance(usage, UsageSummary):
            usage = usage.to_legacy_dict()

        if not isinstance(usage, dict):
            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

        # Try to parse as OpenRouterUsage
        try:
            from src.core.domain.openrouter_usage import OpenRouterUsage

            parsed = OpenRouterUsage.from_dict(usage)
            if parsed is not None:
                result = parsed.to_openrouter_dict()
                # Still apply recalculation logic
                return self._ensure_total_valid(result)
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Failed to parse as OpenRouterUsage", exc_info=True)

        # Fallback to basic normalization
        return self._normalize_basic(usage)

    def _normalize_basic(self, usage: dict[str, Any]) -> dict[str, int]:
        """Normalize usage with basic field coercion.

        Args:
            usage: Usage dictionary

        Returns:
            Normalized usage dictionary
        """
        normalized = dict(usage)

        # Coerce standard fields to integers
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            try:
                value = int(normalized.get(key, 0) or 0)
            except Exception:
                value = 0
            normalized[key] = max(value, 0)

        # Ensure all fields are present
        if "prompt_tokens" not in normalized:
            normalized["prompt_tokens"] = 0
        if "completion_tokens" not in normalized:
            normalized["completion_tokens"] = 0
        if "total_tokens" not in normalized:
            normalized["total_tokens"] = 0

        # Recalculate total if it's less than sum
        normalized = self._ensure_total_valid(normalized)

        return normalized

    def _ensure_total_valid(self, usage: dict[str, Any]) -> dict[str, int]:
        """Ensure total_tokens is valid (at least sum of prompt + completion).

        Args:
            usage: Usage dictionary

        Returns:
            Usage dictionary with valid total_tokens
        """
        prompt = usage.get("prompt_tokens", 0) or 0
        completion = usage.get("completion_tokens", 0) or 0
        total = usage.get("total_tokens", 0) or 0
        summed = prompt + completion
        if total < summed:
            usage["total_tokens"] = summed
        return usage

    def merge_streaming_usage(
        self, existing: dict[str, int], new: dict[str, Any]
    ) -> dict[str, int]:
        """Merge usage keeping highest values.

        Args:
            existing: Existing usage dictionary
            new: New usage dictionary to merge

        Returns:
            Merged usage dictionary with highest values
        """
        # Normalize both, but preserve original totals for merge comparison
        normalized_existing = self._normalize_basic(existing) if existing else {}
        normalized_new = self._normalize_basic(new) if new else {}

        if not normalized_existing and not normalized_new:
            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }

        if not normalized_existing:
            return normalized_new
        if not normalized_new:
            return normalized_existing

        merged = dict(normalized_existing)

        # Keep highest values for token counts
        # Note: We compare the normalized values, which may have been recalculated
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            merged[key] = max(
                normalized_existing.get(key, 0) or 0,
                normalized_new.get(key, 0) or 0,
            )

        # Preserve higher cost when available
        for cost_key in ("cost", "total_cost"):
            prev_cost = normalized_existing.get(cost_key)
            curr_cost = normalized_new.get(cost_key)
            if isinstance(curr_cost, int | float):
                if not isinstance(prev_cost, int | float) or curr_cost > prev_cost:
                    merged[cost_key] = curr_cost
            elif isinstance(prev_cost, int | float):
                merged[cost_key] = prev_cost

        # Preserve extended details from new if not in existing
        for detail_key in (
            "prompt_tokens_details",
            "completion_tokens_details",
            "cost_details",
        ):
            if detail_key not in merged and detail_key in normalized_new:
                merged[detail_key] = normalized_new[detail_key]

        return merged

    def _get_usage_service(self) -> UsageCalculationService | None:
        """Get usage calculation service instance.

        Returns:
            Service instance or None
        """
        if self._usage_service is not None:
            return self._usage_service

        try:
            from src.core.services.usage_calculation_service import (
                get_usage_calculation_service,
            )

            return get_usage_calculation_service()
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Could not get usage calculation service", exc_info=True)
            return None
