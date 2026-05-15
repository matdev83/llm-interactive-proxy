"""Shared runtime state helpers for composite routing."""

from __future__ import annotations

from typing import TypedDict

from src.core.common.exceptions import RoutingError
from src.core.domain.composite_routing import RoutingSurface
from src.core.domain.request_context import RequestContext

__all__ = [
    "COMPOSITE_LEAF_RESOLUTION_EXTRA_BODY_KEY",
    "COMPOSITE_LEAF_RESOLUTION_FLAG",
    "COMPOSITE_LEAF_SELECTOR_EXTRA_BODY_KEY",
    "COMPOSITE_LEAF_PARSED_BACKEND_EXTRA_BODY_KEY",
    "COMPOSITE_LEAF_PARSED_MODEL_EXTRA_BODY_KEY",
    "COMPOSITE_ROUTING_STATE_KEY",
    "COMPOSITE_ROUTING_SURFACE_KEY",
    "COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY",
    "COMPOSITE_SELECTED_LEAF_SELECTOR_KEY",
    "FAILOVER_MODE",
    "FailoverRuntimeState",
    "INTERLEAVED_THINKING_SUPPRESS_THINKER_SELECTION_KEY",
    "WeightedRetryBranch",
    "WEIGHTED_RETRY_MODE",
    "WeightedRetryRuntimeState",
    "build_budget_exhausted_error",
    "build_failover_exhausted_error",
    "contains_top_level_operator",
    "is_composite_selector",
    "resolve_composite_routing_surface",
]

COMPOSITE_ROUTING_STATE_KEY = "composite_routing_state"
COMPOSITE_ROUTING_SURFACE_KEY = "composite_routing_surface"
COMPOSITE_LEAF_RESOLUTION_FLAG = "composite_leaf_resolution"
COMPOSITE_LEAF_RESOLUTION_EXTRA_BODY_KEY = "_composite_leaf_resolution"
COMPOSITE_LEAF_SELECTOR_EXTRA_BODY_KEY = "_composite_leaf_selector"
COMPOSITE_LEAF_PARSED_BACKEND_EXTRA_BODY_KEY = "_composite_leaf_parsed_backend"
COMPOSITE_LEAF_PARSED_MODEL_EXTRA_BODY_KEY = "_composite_leaf_parsed_model"
COMPOSITE_SELECTED_LEAF_SELECTOR_KEY = "composite_selected_leaf_selector"
COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY = "composite_selected_leaf_is_thinker"
INTERLEAVED_THINKING_SUPPRESS_THINKER_SELECTION_KEY = (
    "interleaved_thinking_suppress_thinker_selection"
)
FAILOVER_MODE = "failover"
WEIGHTED_RETRY_MODE = "weighted_retry"


class FailoverRuntimeState(TypedDict):
    """Shared representation of composite failover progress stored in request context."""

    mode: str
    branches: list[str]
    next_index: int
    hop_count: int
    max_hops: int


class WeightedRetryBranch(TypedDict):
    """One weighted leaf stored in request-scoped runtime retry state."""

    selector: str
    weight: int


class WeightedRetryRuntimeState(TypedDict):
    """Runtime snapshot for request-scoped weighted reroll failover.

    Stored under :data:`COMPOSITE_ROUTING_STATE_KEY` with ``mode`` =
    :data:`WEIGHTED_RETRY_MODE`.
    """

    mode: str
    branches: list[WeightedRetryBranch]
    excluded_selectors: list[str]
    selected_selector: str
    hop_count: int
    max_hops: int


def resolve_composite_routing_surface(context: RequestContext | None) -> RoutingSurface:
    """Resolve routing surface from request context metadata."""
    if context is None:
        return RoutingSurface.MAIN

    extensions = getattr(context, "extensions", None)
    if not isinstance(extensions, dict):
        return RoutingSurface.MAIN

    raw_purpose = extensions.get("call_purpose")
    if isinstance(raw_purpose, str) and raw_purpose.startswith("quality_verifier"):
        return RoutingSurface.QUALITY_VERIFIER
    raw_surface = extensions.get(COMPOSITE_ROUTING_SURFACE_KEY)
    if isinstance(raw_surface, str):
        try:
            return RoutingSurface(raw_surface)
        except ValueError:
            pass
    if raw_purpose == "auxiliary":
        return RoutingSurface.AUXILIARY
    if raw_purpose in {"replacement", "model_replacement"}:
        return RoutingSurface.REPLACEMENT_BRIDGE
    return RoutingSurface.MAIN


def contains_top_level_operator(selector: str, operator: str) -> bool:
    """Check whether *operator* appears outside bracket groups in *selector*."""
    bracket_depth = 0
    for char in selector:
        if char == "[":
            bracket_depth += 1
        elif char == "]" and bracket_depth > 0:
            bracket_depth -= 1
        elif char == operator and bracket_depth == 0:
            return True
    return False


def is_composite_selector(model: str) -> bool:
    """Return True when *model* contains a top-level failover or weighted operator.

    Scans the full selector (including query portions) so that composite
    selectors whose first leaf carries query params are correctly detected.
    Operators in query parameter *values* must be URL-encoded (``%5E`` for
    ``^``, ``%7C`` for ``|``) to avoid false positives.
    """
    return contains_top_level_operator(model, "|") or contains_top_level_operator(
        model, "^"
    )


def build_budget_exhausted_error(state: FailoverRuntimeState) -> RoutingError:
    """Build a deterministic error for exhausted composite attempt budget."""
    return RoutingError(
        message="Composite routing attempt budget exhausted.",
        details={
            "code": "temporarily_unavailable",
            "category": "availability",
            "retryable": True,
            "reason": "attempt_budget_exhausted",
            "hop_count": state["hop_count"],
            "max_hops": state["max_hops"],
        },
    )


def build_failover_exhausted_error(state: FailoverRuntimeState) -> RoutingError:
    """Build a deterministic error for exhausted composite failover branches."""
    return RoutingError(
        message="Composite failover branches were exhausted.",
        details={
            "code": "temporarily_unavailable",
            "category": "availability",
            "retryable": True,
            "reason": "failover_exhausted",
            "next_index": state["next_index"],
            "branch_count": len(state["branches"]),
        },
    )
