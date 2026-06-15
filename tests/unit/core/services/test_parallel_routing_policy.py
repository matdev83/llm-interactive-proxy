from __future__ import annotations

import pytest
from src.core.common.exceptions import ValidationError
from src.core.domain.composite_routing import (
    CompositeLeafNode,
    CompositeLeafSelector,
    CompositeParallelGroupNode,
    CompositeRoutePlan,
)
from src.core.services.composite_selector_parser import CompositeSelectorParser
from src.core.services.parallel_routing_policy import (
    ensure_parallel_streaming_supported,
    is_parallel_composite_plan,
)


def _parallel_plan() -> CompositeRoutePlan:
    return CompositeRoutePlan(
        source_selector="openai:gpt-4!anthropic:claude-3",
        normalized_selector="openai:gpt-4!anthropic:claude-3",
        root_node=CompositeParallelGroupNode(
            children=[
                CompositeLeafNode(
                    leaf_selector=CompositeLeafSelector(
                        raw_selector="openai:gpt-4",
                        normalized_selector="openai:gpt-4",
                        uri_params={},
                    )
                ),
                CompositeLeafNode(
                    leaf_selector=CompositeLeafSelector(
                        raw_selector="anthropic:claude-3",
                        normalized_selector="anthropic:claude-3",
                        uri_params={},
                    )
                ),
            ]
        ),
    )


def test_is_parallel_composite_plan_detects_parallel_root_node() -> None:
    assert is_parallel_composite_plan(_parallel_plan()) is True


def test_is_parallel_composite_plan_returns_false_for_failover_plan() -> None:
    parser = CompositeSelectorParser()
    from src.core.domain.composite_routing import CompositeRoutingInput, RoutingSurface

    plan = parser.parse(
        CompositeRoutingInput(
            selector="openai:gpt-4|anthropic:claude-3", surface=RoutingSurface.MAIN
        )
    )
    assert is_parallel_composite_plan(plan) is False


def test_ensure_parallel_streaming_supported_allows_streaming_requests() -> None:
    ensure_parallel_streaming_supported(plan=_parallel_plan(), stream=True)


def test_ensure_parallel_streaming_supported_rejects_non_streaming_requests() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ensure_parallel_streaming_supported(plan=_parallel_plan(), stream=False)

    message = str(exc_info.value).lower()
    assert "parallel" in message
    assert "stream" in message
