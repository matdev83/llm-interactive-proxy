"""Policy helpers for parallel composite routing plans."""

from __future__ import annotations

from src.core.domain.composite_routing import (
    CompositeParallelGroupNode,
    CompositeRoutePlan,
)

__all__ = ["ensure_parallel_streaming_supported", "is_parallel_composite_plan"]


def is_parallel_composite_plan(plan: CompositeRoutePlan) -> bool:
    return isinstance(plan.root_node, CompositeParallelGroupNode)


def ensure_parallel_streaming_supported(
    *,
    plan: CompositeRoutePlan,
    stream: bool,
) -> None:
    if not is_parallel_composite_plan(plan):
        return
    return
