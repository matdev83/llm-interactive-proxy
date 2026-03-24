"""Scaled integer storage for Quality Verifier eligible-turn counting.

Logical "turn units" (1.0 per user step, fractional per tool follow-up) are stored as
integers: ``logical * QV_ELIGIBLE_TURN_SCALE`` to avoid binary floating-point drift in
floors and scheduling logs.
"""

from __future__ import annotations

from typing import Any

# One logical full user turn == SCALE storage units.
QV_ELIGIBLE_TURN_SCALE: int = 1000


def qv_user_turn_increment_scaled() -> int:
    """Storage increment for one eligible user (non-tool-follow-up) turn."""
    return QV_ELIGIBLE_TURN_SCALE


def qv_tool_followup_increment_scaled(weight: float) -> int:
    """Storage increment for one tool-result follow-up; weight in [0.0, 1.0]."""
    try:
        w = float(weight)
    except (TypeError, ValueError):
        w = 0.0
    w = max(0.0, min(1.0, w))
    return max(0, int(round(QV_ELIGIBLE_TURN_SCALE * w)))


def migrate_legacy_eligible_turn_counter(raw: Any) -> int:
    """Normalize persisted or in-memory counter values to scaled integer storage.

    - New format: integer ``>= QV_ELIGIBLE_TURN_SCALE`` (or any int that is already
      a multiple from a previous migration) is kept as-is if already large enough.
    - Legacy whole-turn int in ``[0, SCALE)``: treated as logical full turns.
    - Legacy fractional floats (e.g. ``8.2`` logical): rounded to scaled units.
    - Floats ``>= SCALE`` that are whole numbers: treated as already-scaled storage.
    """
    if raw is None or isinstance(raw, dict | list | bool):
        return 0
    try:
        if isinstance(raw, int):
            if raw < 0:
                return 0
            if raw >= QV_ELIGIBLE_TURN_SCALE:
                return raw
            return raw * QV_ELIGIBLE_TURN_SCALE
        if isinstance(raw, str):
            stripped = raw.strip()
            if not stripped:
                return 0
            v = float(stripped)
        else:
            v = float(raw)
    except (TypeError, ValueError):
        return 0
    if v <= 0:
        return 0
    if v >= float(QV_ELIGIBLE_TURN_SCALE) and abs(v - int(v)) < 1e-9:
        return max(0, int(v))
    return max(0, int(round(v * QV_ELIGIBLE_TURN_SCALE)))


def logical_floor_from_scaled(scaled: int) -> int:
    """Integer logical floor (for frequency modulo) from scaled storage."""
    if scaled <= 0:
        return 0
    return scaled // QV_ELIGIBLE_TURN_SCALE
