"""Coordinator execution for parsed composite routing plans."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol, cast

from pydantic.types import JsonValue

from src.core.common.exceptions import ConfigurationError, RoutingError, ValidationError
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import ChatRequest
from src.core.domain.composite_routing import (
    CompositeBranchOutcomeCategory,
    CompositeFailoverGroupNode,
    CompositeLeafNode,
    CompositeRoutePlan,
    CompositeRoutingAttemptContext,
    CompositeRoutingInput,
    CompositeWeightedGroupNode,
)
from src.core.domain.request_context import RequestContext
from src.core.services.composite_diagnostics_publisher import (
    CompositeDiagnosticsPublisher,
)
from src.core.services.composite_routing_state import (
    COMPOSITE_ROUTING_STATE_KEY,
    FAILOVER_MODE,
    WEIGHTED_RETRY_MODE,
    FailoverRuntimeState,
    WeightedRetryBranch,
    WeightedRetryRuntimeState,
    build_budget_exhausted_error,
    build_failover_exhausted_error,
)
from src.core.services.weighted_branch_selector import WeightedBranchSelector

logger = logging.getLogger(__name__)

__all__ = ["CompositeRoutingCoordinator"]


class _LeafTargetResolver(Protocol):
    async def resolve_leaf(
        self,
        *,
        request: ChatRequest,
        context: RequestContext | None,
        leaf_selector: str,
    ) -> BackendTarget: ...


class CompositeRoutingCoordinator:
    """Executes weighted/failover plans with shared failover state."""

    def __init__(
        self,
        *,
        weighted_branch_selector: WeightedBranchSelector,
        leaf_target_resolver: _LeafTargetResolver,
        diagnostics_publisher: CompositeDiagnosticsPublisher | None = None,
    ) -> None:
        self._weighted_branch_selector = weighted_branch_selector
        self._leaf_target_resolver = leaf_target_resolver
        self._diagnostics_publisher = (
            diagnostics_publisher or CompositeDiagnosticsPublisher()
        )

    async def execute(
        self,
        *,
        plan: CompositeRoutePlan,
        routing_input: CompositeRoutingInput,
        request: ChatRequest,
        context: RequestContext | None,
    ) -> BackendTarget:
        should_publish = self._diagnostics_publisher.should_publish(
            selector=routing_input.selector,
            surface=routing_input.surface,
        )
        root = plan.root_node
        if isinstance(root, CompositeLeafNode):
            resolved = await self._resolve_leaf(
                request=request,
                context=context,
                leaf_node=root,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Composite leaf resolved: surface=%s backend=%s model=%s",
                    routing_input.surface.value,
                    resolved.backend,
                    resolved.model,
                )
            if should_publish:
                self._diagnostics_publisher.publish_selected_target(
                    context=context,
                    selector=routing_input.selector,
                    surface=routing_input.surface,
                    selected_selector=root.leaf_selector.normalized_selector,
                    target=resolved,
                )
            return resolved
        if isinstance(root, CompositeWeightedGroupNode):
            selected_leaf = self._weighted_branch_selector.select(
                root, prefer_first=routing_input.prefer_first_weighted_branch
            )
            resolved = await self._resolve_leaf(
                request=request,
                context=context,
                leaf_node=selected_leaf,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Weighted branch selected: surface=%s selector=%s backend=%s model=%s",
                    routing_input.surface.value,
                    selected_leaf.leaf_selector.normalized_selector,
                    resolved.backend,
                    resolved.model,
                )
            self._persist_weighted_retry_state(
                context=context,
                node=root,
                selected_leaf=selected_leaf,
                configured_max_hops=routing_input.configured_max_hops,
            )
            if should_publish:
                branch_history = [
                    self._branch_history_entry(
                        selector_fragment=leaf.leaf_selector.normalized_selector,
                        outcome_category=(
                            CompositeBranchOutcomeCategory.SELECTED.value
                            if leaf is selected_leaf
                            else CompositeBranchOutcomeCategory.NOT_SELECTED.value
                        ),
                        reason_code=(
                            None
                            if leaf is selected_leaf
                            else "weighted_random_non_winner"
                        ),
                    )
                    for leaf in root.children
                ]
                self._diagnostics_publisher.publish_selected_target(
                    context=context,
                    selector=routing_input.selector,
                    surface=routing_input.surface,
                    selected_selector=selected_leaf.leaf_selector.normalized_selector,
                    target=resolved,
                    branch_history=branch_history,
                )
            return resolved
        if isinstance(root, CompositeFailoverGroupNode):
            return await self._execute_failover_chain(
                node=root,
                routing_input=routing_input,
                request=request,
                context=context,
                should_publish_diagnostics=should_publish,
            )
        raise RoutingError(
            message="Unsupported composite route node encountered.",
            details={
                "code": "routing_validation_failed",
                "reason": "unsupported_node_type",
                "selector": plan.normalized_selector,
            },
        )

    async def _resolve_leaf(
        self,
        *,
        request: ChatRequest,
        context: RequestContext | None,
        leaf_node: CompositeLeafNode,
    ) -> BackendTarget:
        return await self._leaf_target_resolver.resolve_leaf(
            request=request,
            context=context,
            leaf_selector=leaf_node.leaf_selector.normalized_selector,
        )

    async def _execute_failover_chain(
        self,
        *,
        node: CompositeFailoverGroupNode,
        routing_input: CompositeRoutingInput,
        request: ChatRequest,
        context: RequestContext | None,
        should_publish_diagnostics: bool,
    ) -> BackendTarget:
        branches = [child.leaf_selector.normalized_selector for child in node.children]
        state = self._load_or_init_state(
            context=context,
            branches=branches,
            configured_max_hops=routing_input.configured_max_hops,
        )
        branch_index = min(max(0, state["next_index"]), len(node.children))
        branch_history: list[dict[str, JsonValue]] = []
        branch_history_omitted = 0
        history_limit = routing_input.max_branch_history
        if should_publish_diagnostics and branch_index > 0:
            for skipped_selector in branches[:branch_index]:
                branch_history_omitted = self._append_branch_history(
                    branch_history=branch_history,
                    entry=self._branch_history_entry(
                        selector_fragment=skipped_selector,
                        outcome_category=CompositeBranchOutcomeCategory.INELIGIBLE.value,
                        reason_code="already_attempted",
                    ),
                    limit=history_limit,
                    omitted=branch_history_omitted,
                )

        if branch_index >= len(node.children):
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Composite failover exhausted on entry: surface=%s branches=%d",
                    routing_input.surface.value,
                    len(state["branches"]),
                )
            if should_publish_diagnostics:
                self._diagnostics_publisher.publish_exhaustion(
                    context=context,
                    selector=routing_input.selector,
                    surface=routing_input.surface,
                    reason="failover_exhausted",
                    details={
                        "next_index": state["next_index"],
                        "branch_count": len(state["branches"]),
                    },
                    branch_history=branch_history,
                    branch_history_omitted=branch_history_omitted,
                )
            raise build_failover_exhausted_error(state)

        while branch_index < len(node.children):
            current_branch = node.children[branch_index]
            try:
                resolved = await self._resolve_leaf(
                    request=request,
                    context=context,
                    leaf_node=current_branch,
                )
                if should_publish_diagnostics:
                    branch_history_omitted = self._append_branch_history(
                        branch_history=branch_history,
                        entry=self._branch_history_entry(
                            selector_fragment=current_branch.leaf_selector.normalized_selector,
                            outcome_category=CompositeBranchOutcomeCategory.SELECTED.value,
                            backend=resolved.backend,
                            model=resolved.model,
                        ),
                        limit=history_limit,
                        omitted=branch_history_omitted,
                    )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failover branch resolved: surface=%s index=%d selector=%s backend=%s model=%s",
                        routing_input.surface.value,
                        branch_index,
                        current_branch.leaf_selector.normalized_selector,
                        resolved.backend,
                        resolved.model,
                    )
                state["next_index"] = branch_index + 1
                self._persist_state(context=context, state=state)
                if should_publish_diagnostics:
                    self._diagnostics_publisher.publish_selected_target(
                        context=context,
                        selector=routing_input.selector,
                        surface=routing_input.surface,
                        selected_selector=current_branch.leaf_selector.normalized_selector,
                        target=resolved,
                        branch_history=branch_history,
                        branch_history_omitted=branch_history_omitted,
                    )
                return resolved
            except Exception as branch_error:
                if not self._is_failover_eligible_leaf_resolution_error(branch_error):
                    raise
                outcome_category, reason_code = self._classify_branch_error(
                    branch_error
                )
                if should_publish_diagnostics:
                    branch_history_omitted = self._append_branch_history(
                        branch_history=branch_history,
                        entry=self._branch_history_entry(
                            selector_fragment=current_branch.leaf_selector.normalized_selector,
                            outcome_category=outcome_category,
                            reason_code=reason_code,
                        ),
                        limit=history_limit,
                        omitted=branch_history_omitted,
                    )
                if state["hop_count"] >= state["max_hops"]:
                    self._persist_state(context=context, state=state)
                    if should_publish_diagnostics:
                        exhaustion_history = [
                            *branch_history,
                            self._branch_history_entry(
                                selector_fragment=current_branch.leaf_selector.normalized_selector,
                                outcome_category=CompositeBranchOutcomeCategory.EXHAUSTED.value,
                                reason_code="attempt_budget_exhausted",
                            ),
                        ]
                        exhaustion_omitted = branch_history_omitted
                        if len(exhaustion_history) > history_limit:
                            overflow = len(exhaustion_history) - history_limit
                            del exhaustion_history[:overflow]
                            exhaustion_omitted += overflow
                        self._diagnostics_publisher.publish_exhaustion(
                            context=context,
                            selector=routing_input.selector,
                            surface=routing_input.surface,
                            reason="attempt_budget_exhausted",
                            details={
                                "hop_count": state["hop_count"],
                                "max_hops": state["max_hops"],
                            },
                            branch_history=exhaustion_history,
                            branch_history_omitted=exhaustion_omitted,
                        )
                    raise build_budget_exhausted_error(state) from branch_error
                if branch_index >= len(node.children) - 1:
                    state["next_index"] = len(node.children)
                    self._persist_state(context=context, state=state)
                    if should_publish_diagnostics:
                        exhaustion_history = [
                            *branch_history,
                            self._branch_history_entry(
                                selector_fragment=current_branch.leaf_selector.normalized_selector,
                                outcome_category=CompositeBranchOutcomeCategory.EXHAUSTED.value,
                                reason_code="failover_exhausted",
                            ),
                        ]
                        exhaustion_omitted = branch_history_omitted
                        if len(exhaustion_history) > history_limit:
                            overflow = len(exhaustion_history) - history_limit
                            del exhaustion_history[:overflow]
                            exhaustion_omitted += overflow
                        self._diagnostics_publisher.publish_exhaustion(
                            context=context,
                            selector=routing_input.selector,
                            surface=routing_input.surface,
                            reason="failover_exhausted",
                            details={
                                "next_index": state["next_index"],
                                "branch_count": len(state["branches"]),
                            },
                            branch_history=exhaustion_history,
                            branch_history_omitted=exhaustion_omitted,
                        )
                    raise build_failover_exhausted_error(state) from branch_error
                state["hop_count"] += 1
                state["next_index"] = branch_index + 1
                self._persist_state(context=context, state=state)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failover advancing: surface=%s hop=%d/%d next_index=%d",
                        routing_input.surface.value,
                        state["hop_count"],
                        state["max_hops"],
                        state["next_index"],
                    )
                branch_index += 1

        if should_publish_diagnostics:
            self._diagnostics_publisher.publish_exhaustion(
                context=context,
                selector=routing_input.selector,
                surface=routing_input.surface,
                reason="failover_exhausted",
                details={
                    "next_index": state["next_index"],
                    "branch_count": len(state["branches"]),
                },
                branch_history=branch_history,
                branch_history_omitted=branch_history_omitted,
            )
        raise build_failover_exhausted_error(state)

    @staticmethod
    def _append_branch_history(
        *,
        branch_history: list[dict[str, JsonValue]],
        entry: dict[str, JsonValue],
        limit: int,
        omitted: int,
    ) -> int:
        branch_history.append(entry)
        if len(branch_history) <= limit:
            return omitted
        overflow = len(branch_history) - limit
        if overflow > 0:
            del branch_history[:overflow]
            return omitted + overflow
        return omitted

    @staticmethod
    def _is_failover_eligible_leaf_resolution_error(error: Exception) -> bool:
        """Return True only for routing/validation/configuration outcomes.

        Unexpected bugs or infrastructure failures from leaf resolution must not
        consume failover hop budget or mask the underlying exception.
        """
        return isinstance(error, RoutingError | ValidationError | ConfigurationError)

    def _classify_branch_error(self, error: Exception) -> tuple[str, str]:
        reason_code = self._extract_reason_code(error)
        if isinstance(error, RoutingError):
            details = error.details if isinstance(error.details, dict) else {}
            category = details.get("category")
            if category == "validation" or reason_code == "unknown_model":
                return (
                    CompositeBranchOutcomeCategory.VALIDATION_REJECTED.value,
                    reason_code,
                )
            if category == "availability" or reason_code == "temporarily_unavailable":
                return CompositeBranchOutcomeCategory.INELIGIBLE.value, reason_code
        if isinstance(error, ValidationError | ConfigurationError):
            return CompositeBranchOutcomeCategory.VALIDATION_REJECTED.value, reason_code
        return CompositeBranchOutcomeCategory.RUNTIME_FAILED.value, reason_code

    @staticmethod
    def _branch_history_entry(
        *,
        selector_fragment: str,
        outcome_category: str,
        reason_code: str | None = None,
        backend: str | None = None,
        model: str | None = None,
    ) -> dict[str, JsonValue]:
        entry: dict[str, JsonValue] = {
            "selector_fragment": selector_fragment,
            "outcome_category": outcome_category,
        }
        if reason_code:
            entry["reason_code"] = reason_code
        if backend:
            entry["backend"] = backend
        if model:
            entry["model"] = model
        return entry

    @staticmethod
    def _extract_reason_code(error: Exception) -> str:
        if isinstance(error, RoutingError):
            details = error.details if isinstance(error.details, dict) else {}
            code = details.get("code")
            if isinstance(code, str) and code.strip():
                return code.strip()
        return type(error).__name__

    @staticmethod
    def _load_or_init_state(
        *,
        context: RequestContext | None,
        branches: Sequence[str],
        configured_max_hops: int | None,
    ) -> FailoverRuntimeState:
        default_max_hops = CompositeRoutingAttemptContext.resolve_max_hops(
            configured_max_hops
        )
        if context is None:
            return {
                "mode": FAILOVER_MODE,
                "branches": list(branches),
                "next_index": 0,
                "hop_count": 0,
                "max_hops": default_max_hops,
            }

        raw_state = context.extensions.get(COMPOSITE_ROUTING_STATE_KEY)
        if isinstance(raw_state, dict):
            mode = raw_state.get("mode")
            stored_branches = raw_state.get("branches")
            stored_next_index = raw_state.get("next_index")
            stored_hop_count = raw_state.get("hop_count")
            stored_max_hops = raw_state.get("max_hops")
            if (
                mode == FAILOVER_MODE
                and isinstance(stored_branches, list)
                and all(isinstance(item, str) for item in stored_branches)
                and list(stored_branches) == list(branches)
                and isinstance(stored_next_index, int)
                and isinstance(stored_hop_count, int)
                and isinstance(stored_max_hops, int)
                and stored_next_index >= 0
                and stored_hop_count >= 0
                and stored_max_hops > 0
            ):
                return {
                    "mode": FAILOVER_MODE,
                    "branches": cast(list[str], stored_branches),
                    "next_index": min(stored_next_index, len(branches)),
                    "hop_count": stored_hop_count,
                    "max_hops": stored_max_hops,
                }

        initialized: FailoverRuntimeState = {
            "mode": FAILOVER_MODE,
            "branches": list(branches),
            "next_index": 0,
            "hop_count": 0,
            "max_hops": default_max_hops,
        }
        context.extensions[COMPOSITE_ROUTING_STATE_KEY] = cast(JsonValue, initialized)
        return initialized

    @staticmethod
    def _persist_weighted_retry_state(
        *,
        context: RequestContext | None,
        node: CompositeWeightedGroupNode,
        selected_leaf: CompositeLeafNode,
        configured_max_hops: int | None,
    ) -> None:
        if context is None:
            return
        branches: list[WeightedRetryBranch] = []
        for child in node.children:
            raw = child.leaf_selector.weight_annotation
            resolved_weight = 1 if raw is None else raw
            branches.append(
                {
                    "selector": child.leaf_selector.normalized_selector,
                    "weight": resolved_weight,
                }
            )
        max_hops = CompositeRoutingAttemptContext.resolve_max_hops(configured_max_hops)
        persisted: WeightedRetryRuntimeState = {
            "mode": WEIGHTED_RETRY_MODE,
            "branches": branches,
            "excluded_selectors": [],
            "selected_selector": selected_leaf.leaf_selector.normalized_selector,
            "hop_count": 0,
            "max_hops": max_hops,
        }
        context.extensions[COMPOSITE_ROUTING_STATE_KEY] = cast(JsonValue, persisted)

    @staticmethod
    def _persist_state(
        *,
        context: RequestContext | None,
        state: FailoverRuntimeState,
    ) -> None:
        if context is None:
            return
        context.extensions[COMPOSITE_ROUTING_STATE_KEY] = cast(
            JsonValue,
            {
                "mode": FAILOVER_MODE,
                "branches": list(state["branches"]),
                "next_index": state["next_index"],
                "hop_count": state["hop_count"],
                "max_hops": state["max_hops"],
            },
        )
