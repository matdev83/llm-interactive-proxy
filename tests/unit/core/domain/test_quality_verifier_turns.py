"""Tests for scaled Quality Verifier eligible-turn storage."""

from __future__ import annotations

import pytest
from src.core.domain.quality_verifier_turns import (
    QV_ELIGIBLE_TURN_SCALE,
    logical_floor_from_scaled,
    migrate_legacy_eligible_turn_counter,
    qv_tool_followup_increment_scaled,
    qv_user_turn_increment_scaled,
)


def test_user_increment_matches_scale() -> None:
    assert qv_user_turn_increment_scaled() == QV_ELIGIBLE_TURN_SCALE


def test_tool_increment_default_weight() -> None:
    # Default session weight 0.2 -> 200 units
    assert qv_tool_followup_increment_scaled(0.2) == 200


def test_migrate_legacy_float() -> None:
    assert migrate_legacy_eligible_turn_counter(8.2) == 8200


def test_migrate_legacy_small_int_whole_turns() -> None:
    assert migrate_legacy_eligible_turn_counter(9) == 9000


def test_migrate_already_scaled() -> None:
    assert migrate_legacy_eligible_turn_counter(8200) == 8200


def test_logical_floor() -> None:
    assert logical_floor_from_scaled(0) == 0
    assert logical_floor_from_scaled(999) == 0
    assert logical_floor_from_scaled(1000) == 1
    assert logical_floor_from_scaled(10_000) == 10


@pytest.mark.parametrize(
    ("weight", "expected"),
    [
        (0.0, 0),
        (1.0, QV_ELIGIBLE_TURN_SCALE),
        (0.15, 150),
    ],
)
def test_tool_increment_clamped(weight: float, expected: int) -> None:
    assert qv_tool_followup_increment_scaled(weight) == expected
