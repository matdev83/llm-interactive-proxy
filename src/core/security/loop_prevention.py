"""Utilities for preventing backend request loops."""

from __future__ import annotations

from collections.abc import Mapping

LOOP_GUARD_HEADER = "x-llmproxy-loop-guard"
LOOP_GUARD_VALUE = "1"


def ensure_loop_guard_header(headers: Mapping[str, str] | None) -> dict[str, str]:
    """Return headers with the loop guard marker applied."""
    result: dict[str, str] = dict(headers.items()) if headers else {}
    result.setdefault(LOOP_GUARD_HEADER, LOOP_GUARD_VALUE)
    return result
