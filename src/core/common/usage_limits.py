"""Utilities for normalizing usage-related request parameters."""

from __future__ import annotations

from typing import Any

from src.constants import MAX_RECENT_USAGE_RECORDS


def normalize_recent_usage_limit(limit: Any) -> int:
    """Normalize the recent usage limit value to a safe, bounded integer.

    Args:
        limit: The requested limit value that may come from untrusted sources.

    Returns:
        A non-negative integer that does not exceed :data:`MAX_RECENT_USAGE_RECORDS`.
        Invalid or non-positive values yield ``0`` so callers can short-circuit expensive
        repository lookups.
    """

    try:
        numeric_limit = int(limit)
    except (TypeError, ValueError):
        return 0

    if numeric_limit <= 0:
        return 0

    return min(numeric_limit, MAX_RECENT_USAGE_RECORDS)
