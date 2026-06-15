from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.core.domain.composite_routing import (
    CompositeLeafNode,
    CompositeLeafSelector,
    CompositeParallelGroupNode,
    CompositeRoutePlan,
)


def _parallel_leaf(
    *,
    selector: str,
    handicap_seconds: float = 0.0,
    ttft_timeout_seconds: float = 0.0,
) -> CompositeLeafNode:
    return CompositeLeafNode(
        leaf_selector=CompositeLeafSelector(
            raw_selector=selector,
            normalized_selector=selector,
            handicap_seconds=handicap_seconds,
            ttft_timeout_seconds=ttft_timeout_seconds,
            uri_params={},
        )
    )


def test_composite_parallel_group_node_requires_at_least_two_branches() -> None:
    with pytest.raises(ValidationError):
        CompositeParallelGroupNode(children=[_parallel_leaf(selector="openai:gpt-4")])


def test_composite_parallel_group_node_serializes_with_parallel_kind() -> None:
    plan = CompositeRoutePlan(
        source_selector="openai:gpt-4!anthropic:claude-3",
        normalized_selector="openai:gpt-4!anthropic:claude-3",
        root_node=CompositeParallelGroupNode(
            children=[
                _parallel_leaf(selector="openai:gpt-4"),
                _parallel_leaf(selector="anthropic:claude-3"),
            ]
        ),
    )

    dumped = plan.model_dump()
    assert dumped["root_node"]["kind"] == "parallel_group"
    assert len(dumped["root_node"]["children"]) == 2


def test_composite_leaf_selector_parallel_timing_defaults_to_zero() -> None:
    leaf = CompositeLeafSelector(
        raw_selector="openai:gpt-4",
        normalized_selector="openai:gpt-4",
        uri_params={},
    )

    assert leaf.handicap_seconds == 0.0
    assert leaf.ttft_timeout_seconds == 0.0


@pytest.mark.parametrize(
    ("handicap_seconds", "ttft_timeout_seconds"),
    [
        (0, 0),
        (0.0, 0.0),
        (1, 2),
        (0.5, 3.25),
    ],
)
def test_composite_leaf_selector_accepts_non_negative_parallel_timing(
    handicap_seconds: float,
    ttft_timeout_seconds: float,
) -> None:
    leaf = CompositeLeafSelector(
        raw_selector="openai:gpt-4",
        normalized_selector="openai:gpt-4",
        handicap_seconds=handicap_seconds,
        ttft_timeout_seconds=ttft_timeout_seconds,
        uri_params={},
    )

    assert leaf.handicap_seconds == float(handicap_seconds)
    assert leaf.ttft_timeout_seconds == float(ttft_timeout_seconds)


@pytest.mark.parametrize(
    "field_name",
    ["handicap_seconds", "ttft_timeout_seconds"],
)
@pytest.mark.parametrize("invalid_value", [-1, -0.1])
def test_composite_leaf_selector_rejects_negative_parallel_timing(
    field_name: str,
    invalid_value: float,
) -> None:
    with pytest.raises(ValidationError):
        CompositeLeafSelector(
            raw_selector="openai:gpt-4",
            normalized_selector="openai:gpt-4",
            uri_params={},
            **{field_name: invalid_value},
        )
