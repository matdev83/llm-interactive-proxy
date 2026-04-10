"""Weighted branch selection service for composite routing."""

from __future__ import annotations

import random
from collections.abc import Callable

from src.core.domain.composite_routing import (
    CompositeLeafNode,
    CompositeWeightedGroupNode,
)

__all__ = ["WeightedBranchSelector"]


class WeightedBranchSelector:
    """Select exactly one weighted branch using an injectable random boundary."""

    def __init__(
        self,
        random_value_provider: Callable[[], float] | None = None,
    ) -> None:
        self._random_value_provider = random_value_provider or random.random

    def select(self, weighted_node: CompositeWeightedGroupNode) -> CompositeLeafNode:
        if not weighted_node.children:
            raise ValueError("Weighted node must contain at least one branch.")

        normalized_weights: list[int] = []
        for branch in weighted_node.children:
            weight = branch.leaf_selector.weight_annotation
            resolved_weight = 1 if weight is None else weight
            if resolved_weight <= 0:
                raise ValueError(
                    f"Invalid branch weight {resolved_weight}; weights must be positive."
                )
            normalized_weights.append(resolved_weight)

        total_weight = sum(normalized_weights)
        if total_weight <= 0:
            raise ValueError("Weighted node must have a positive total weight.")

        random_value = float(self._random_value_provider())
        if random_value < 0.0:
            random_value = 0.0
        elif random_value >= 1.0:
            # Clamp to keep deterministic selection in [0, 1) when test doubles
            # return boundary or out-of-range values.
            random_value = 0.9999999999999999

        threshold = random_value * total_weight
        cumulative_weight = 0.0

        for branch, weight in zip(
            weighted_node.children, normalized_weights, strict=True
        ):
            cumulative_weight += weight
            if threshold < cumulative_weight:
                return branch

        # Floating-point edge case fallback: return the final branch deterministically.
        return weighted_node.children[-1]
