from __future__ import annotations

from collections import Counter

import pytest
from src.core.domain.composite_routing import (
    CompositeLeafNode,
    CompositeLeafSelector,
    CompositeWeightedGroupNode,
)
from src.core.services.weighted_branch_selector import WeightedBranchSelector


def _leaf(selector: str, weight: int) -> CompositeLeafNode:
    return CompositeLeafNode(
        leaf_selector=CompositeLeafSelector(
            raw_selector=selector,
            normalized_selector=selector,
            weight_annotation=weight,
            uri_params={},
            backend_type="openai",
            model_name=selector,
        )
    )


def test_weighted_selection_is_deterministic_with_injected_randomness() -> None:
    selector = CompositeWeightedGroupNode(
        children=[
            _leaf("gpt-4o-mini", 1),
            _leaf("claude-3-5-sonnet", 3),
        ]
    )
    random_values = iter([0.0, 0.20, 0.80])
    service = WeightedBranchSelector(random_value_provider=lambda: next(random_values))

    first = service.select(selector)
    second = service.select(selector)
    third = service.select(selector)

    assert first.leaf_selector.normalized_selector == "gpt-4o-mini"
    assert second.leaf_selector.normalized_selector == "gpt-4o-mini"
    assert third.leaf_selector.normalized_selector == "claude-3-5-sonnet"


def test_weighted_selection_bias_respects_relative_weights() -> None:
    selector = CompositeWeightedGroupNode(
        children=[
            _leaf("small", 1),
            _leaf("large", 3),
        ]
    )
    random_values = iter([index / 100 for index in range(100)])
    service = WeightedBranchSelector(random_value_provider=lambda: next(random_values))

    counts: Counter[str] = Counter()
    for _ in range(100):
        selected = service.select(selector)
        counts[selected.leaf_selector.normalized_selector] += 1

    assert counts["small"] == 25
    assert counts["large"] == 75


def test_weighted_selection_returns_exactly_one_branch_per_decision() -> None:
    selector = CompositeWeightedGroupNode(
        children=[
            _leaf("branch-a", 2),
            _leaf("branch-b", 2),
            _leaf("branch-c", 2),
        ]
    )
    random_values = iter([0.05, 0.40, 0.65, 0.95])
    service = WeightedBranchSelector(random_value_provider=lambda: next(random_values))

    selected = [service.select(selector) for _ in range(4)]

    assert len(selected) == 4
    assert all(isinstance(branch, CompositeLeafNode) for branch in selected)
    assert {branch.leaf_selector.normalized_selector for branch in selected}.issubset(
        {"branch-a", "branch-b", "branch-c"}
    )


def test_weighted_selection_guards_against_non_positive_weights() -> None:
    invalid_leaf = _leaf("invalid", 1).model_copy(
        update={
            "leaf_selector": _leaf("invalid", 1).leaf_selector.model_copy(
                update={"weight_annotation": 0}
            )
        }
    )
    selector = CompositeWeightedGroupNode(children=[_leaf("valid", 1), invalid_leaf])
    service = WeightedBranchSelector(random_value_provider=lambda: 0.5)

    with pytest.raises(ValueError):
        service.select(selector)
