"""Unit tests for Responses session resolution helpers."""

from __future__ import annotations

from src.core.domain.responses_resolved_session import (
    effective_instructions_for_chained_turn,
)


def test_effective_instructions_new_replaces_prior() -> None:
    assert effective_instructions_for_chained_turn("new", "old") == "new"


def test_effective_instructions_omitted_inherits_prior() -> None:
    assert effective_instructions_for_chained_turn(None, "old") == "old"


def test_effective_instructions_no_prior() -> None:
    assert effective_instructions_for_chained_turn("only", None) == "only"
    assert effective_instructions_for_chained_turn(None, None) is None
