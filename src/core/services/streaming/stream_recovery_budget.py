"""Helpers for persisted stream recovery budget metadata."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import cast

from pydantic.types import JsonValue

from src.core.domain.request_context import RequestContext

_BUDGET_START_TIME_KEY = "recovery_budget_start_time"
_ATTEMPTED_BACKENDS_KEY = "attempted_backends"
_RETRY_ATTEMPT_KEY = "retry_attempt"
_MEANINGFUL_OUTPUT_EMITTED_KEY = "meaningful_output_emitted"


@dataclass(slots=True)
class StreamRecoveryBudget:
    """Persisted recovery budget fields shared across recursive attempts."""

    budget_start_time: float
    attempted_backends: list[str]
    retry_attempt: int
    meaningful_output_emitted: bool


def _coerce_retry_attempt(value: object) -> int:
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float) and value.is_integer():
        return max(0, int(value))
    if isinstance(value, str) and value.strip():
        try:
            return max(0, int(value.strip()))
        except ValueError:
            return 0
    return 0


def get_or_init_stream_recovery_budget(
    context: RequestContext | None,
) -> StreamRecoveryBudget | None:
    """Return persisted stream recovery budget from request context extensions."""
    if context is None:
        return None

    extensions = context.extensions

    if _BUDGET_START_TIME_KEY not in extensions:
        extensions[_BUDGET_START_TIME_KEY] = float(time.time())
    if _ATTEMPTED_BACKENDS_KEY not in extensions:
        extensions[_ATTEMPTED_BACKENDS_KEY] = []
    if _RETRY_ATTEMPT_KEY not in extensions:
        extensions[_RETRY_ATTEMPT_KEY] = 0
    if _MEANINGFUL_OUTPUT_EMITTED_KEY not in extensions:
        extensions[_MEANINGFUL_OUTPUT_EMITTED_KEY] = False

    budget_start_raw = extensions.get(_BUDGET_START_TIME_KEY)
    if isinstance(budget_start_raw, int | float):
        budget_start_time = float(budget_start_raw)
    else:
        budget_start_time = float(time.time())
        extensions[_BUDGET_START_TIME_KEY] = budget_start_time

    attempted_backends_raw = extensions.get(_ATTEMPTED_BACKENDS_KEY)
    attempted_backends: list[str] = []
    if isinstance(attempted_backends_raw, list):
        if all(isinstance(item, str) for item in attempted_backends_raw):
            attempted_backends = cast(list[str], attempted_backends_raw)
        else:
            attempted_backends = [
                item for item in attempted_backends_raw if isinstance(item, str)
            ]
            extensions[_ATTEMPTED_BACKENDS_KEY] = cast(JsonValue, attempted_backends)
    else:
        extensions[_ATTEMPTED_BACKENDS_KEY] = cast(JsonValue, attempted_backends)

    retry_attempt = _coerce_retry_attempt(extensions.get(_RETRY_ATTEMPT_KEY))
    extensions[_RETRY_ATTEMPT_KEY] = retry_attempt

    meaningful_output_raw = extensions.get(_MEANINGFUL_OUTPUT_EMITTED_KEY)
    meaningful_output_emitted = (
        meaningful_output_raw if isinstance(meaningful_output_raw, bool) else False
    )
    extensions[_MEANINGFUL_OUTPUT_EMITTED_KEY] = meaningful_output_emitted

    return StreamRecoveryBudget(
        budget_start_time=budget_start_time,
        attempted_backends=attempted_backends,
        retry_attempt=retry_attempt,
        meaningful_output_emitted=meaningful_output_emitted,
    )


def mark_stream_meaningful_output(context: RequestContext | None) -> None:
    """Persist a marker indicating stream output already became meaningful."""
    if context is None:
        return

    get_or_init_stream_recovery_budget(context)
    context.extensions[_MEANINGFUL_OUTPUT_EMITTED_KEY] = True


__all__ = [
    "StreamRecoveryBudget",
    "get_or_init_stream_recovery_budget",
    "mark_stream_meaningful_output",
]
