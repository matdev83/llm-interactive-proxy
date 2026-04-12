"""Weighted branch selection service for composite routing."""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence

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

    def select_index_from_weights(self, weights: Sequence[int]) -> int:
        """Return a branch index using the same RNG and cumulative rule as :meth:`select`.

        For callers that only have a plain positive integer weight vector (e.g. bridge
        layers) without a :class:`CompositeWeightedGroupNode`. Does not alter
        :meth:`select` behavior.
        """
        if not weights:
            raise ValueError("Weighted selection requires at least one weight.")

        normalized_weights: list[int] = []
        for resolved_weight in weights:
            if resolved_weight <= 0:
                raise ValueError(
                    f"Invalid branch weight {resolved_weight}; weights must be positive."
                )
            normalized_weights.append(resolved_weight)

        total_weight = sum(normalized_weights)
        if total_weight <= 0:
            raise ValueError("Weighted selection must have a positive total weight.")

        random_value = float(self._random_value_provider())
        if random_value < 0.0:
            random_value = 0.0
        elif random_value >= 1.0:
            random_value = 0.9999999999999999

        threshold = random_value * total_weight
        cumulative_weight = 0.0

        for index, weight in enumerate(normalized_weights):
            cumulative_weight += weight
            if threshold < cumulative_weight:
                return index

        return len(normalized_weights) - 1

    def select(
        self,
        weighted_node: CompositeWeightedGroupNode,
        *,
        prefer_first: bool = False,
    ) -> CompositeLeafNode:
        if not weighted_node.children:
            raise ValueError("Weighted node must contain at least one branch.")

        if prefer_first:
            first_branches = [
                child
                for child in weighted_node.children
                if child.leaf_selector.first_annotation
            ]
            if len(first_branches) == 1:
                return first_branches[0]
            if len(first_branches) > 1:
                raise ValueError(
                    "multiple branches annotated with [first]; "
                    "exactly one is required when prefer_first is enabled"
                )
            # No first_annotation found — fall through to weighted selection

        normalized_weights: list[int] = []
        for branch in weighted_node.children:
            weight = branch.leaf_selector.weight_annotation
            resolved_weight = 1 if weight is None else weight
            if resolved_weight <= 0:
                raise ValueError(
                    f"Invalid branch weight {resolved_weight}; weights must be positive."
                )
            normalized_weights.append(resolved_weight)

        index = self.select_index_from_weights(normalized_weights)
        return weighted_node.children[index]
