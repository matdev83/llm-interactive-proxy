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
    CompositeLeafSelector,
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
    COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY,
    COMPOSITE_SELECTED_LEAF_SELECTOR_KEY,
    FAILOVER_MODE,
    INTERLEAVED_THINKING_SUPPRESS_THINKER_SELECTION_KEY,
    INTERLEAVED_THINKING_WEIGHTED_CYCLE_STATE_KEY,
    WEIGHTED_RETRY_MODE,
    FailoverRuntimeState,
    WeightedRetryBranch,
    WeightedRetryRuntimeState,
    build_budget_exhausted_error,
    build_failover_exhausted_error,
)
from src.core.services.weighted_branch_selector import WeightedBranchSelector
from src.core.utils.token_count import count_tokens, extract_prompt_text

logger = logging.getLogger(__name__)

__all__ = ["CompositeRoutingCoordinator"]


class _LeafTargetResolver(Protocol):
    async def resolve_leaf(
        self,
        *,
        request: ChatRequest,
        context: RequestContext | None,
        leaf: CompositeLeafSelector,
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
            if not self._is_branch_eligible_for_max_context(
                leaf=root,
                request_context_tokens=routing_input.request_context_tokens,
                request=request,
                token_cache={},
            ):
                if should_publish:
                    self._diagnostics_publisher.publish_exhaustion(
                        context=context,
                        selector=routing_input.selector,
                        surface=routing_input.surface,
                        reason="max_context_exceeded",
                        details={
                            "request_context_tokens": routing_input.request_context_tokens,
                            "max_context_tokens": root.leaf_selector.max_context_tokens,
                        },
                        branch_history=[
                            self._branch_history_entry(
                                selector_fragment=root.leaf_selector.normalized_selector,
                                outcome_category=CompositeBranchOutcomeCategory.INELIGIBLE.value,
                                reason_code="max_context_exceeded",
                            )
                        ],
                    )
                raise RoutingError(
                    message="Leaf selector exceeded max_context constraint.",
                    details={
                        "code": "temporarily_unavailable",
                        "category": "availability",
                        "retryable": True,
                        "reason": "max_context_exceeded",
                    },
                )
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
            # Evaluate max_context eligibility for this request before weighted selection.
            token_cache: dict[str, int] = {}
            eligible_weighted_children, filtered_weighted_history = (
                self._filter_children_by_max_context(
                    children=root.children,
                    request_context_tokens=routing_input.request_context_tokens,
                    request=request,
                    token_cache=token_cache,
                )
            )
            if not eligible_weighted_children:
                if should_publish:
                    self._diagnostics_publisher.publish_exhaustion(
                        context=context,
                        selector=routing_input.selector,
                        surface=routing_input.surface,
                        reason="max_context_exhausted",
                        details={
                            "request_context_tokens": routing_input.request_context_tokens,
                            "branch_count": len(root.children),
                        },
                        branch_history=filtered_weighted_history,
                    )
                raise RoutingError(
                    message="All weighted branches exceeded max_context constraints.",
                    details={
                        "code": "temporarily_unavailable",
                        "category": "availability",
                        "retryable": True,
                        "reason": "max_context_exhausted",
                    },
                )

            has_thinker_branch = self._has_thinker_branch(root.children)
            if (
                has_thinker_branch
                and self._should_suppress_thinker_selection(context)
                and not any(
                    not child.leaf_selector.thinker_annotation
                    for child in eligible_weighted_children
                )
            ):
                eligible_weighted_children = []
            elif not has_thinker_branch:
                eligible_weighted_children = self._filter_thinker_children_if_needed(
                    context=context,
                    children=eligible_weighted_children,
                )
            if not eligible_weighted_children:
                if should_publish:
                    self._diagnostics_publisher.publish_exhaustion(
                        context=context,
                        selector=routing_input.selector,
                        surface=routing_input.surface,
                        reason="interleaved_thinking_suppressed",
                        details={
                            "branch_count": len(root.children),
                            "request_context_tokens": routing_input.request_context_tokens,
                        },
                        branch_history=[
                            *filtered_weighted_history,
                            *(
                                self._branch_history_entry(
                                    selector_fragment=leaf.leaf_selector.normalized_selector,
                                    outcome_category=CompositeBranchOutcomeCategory.INELIGIBLE.value,
                                    reason_code="interleaved_thinking_suppressed",
                                )
                                for leaf in root.children
                                if leaf.leaf_selector.thinker_annotation
                            ),
                        ],
                    )
                raise RoutingError(
                    message=(
                        "All weighted branches were excluded by interleaved thinking suppression."
                    ),
                    details={
                        "code": "temporarily_unavailable",
                        "category": "availability",
                        "retryable": True,
                        "reason": "interleaved_thinking_suppressed",
                    },
                )
            if has_thinker_branch:
                selected_leaf = self._select_interleaved_thinking_weighted_cycle_leaf(
                    children=eligible_weighted_children,
                    selector=plan.normalized_selector,
                    cycle_state=routing_input.interleaved_thinking_weighted_cycle_state,
                    prefer_first=routing_input.prefer_first_weighted_branch,
                    context=context,
                )
            elif len(eligible_weighted_children) == 1:
                selected_leaf = eligible_weighted_children[0]
            else:
                selected_leaf = self._weighted_branch_selector.select(
                    CompositeWeightedGroupNode(
                        children=list(eligible_weighted_children)
                    ),
                    prefer_first=routing_input.prefer_first_weighted_branch,
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
                eligible_leaves=eligible_weighted_children,
                selected_leaf=selected_leaf,
                configured_max_hops=routing_input.configured_max_hops,
            )
            if should_publish:
                branch_history = list(filtered_weighted_history)
                branch_history.extend(
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
                            else (
                                "interleaved_thinking_weighted_cycle_non_winner"
                                if has_thinker_branch
                                else "weighted_random_non_winner"
                            )
                        ),
                    )
                    for leaf in eligible_weighted_children
                )
                self._diagnostics_publisher.publish_selected_target(
                    context=context,
                    selector=routing_input.selector,
                    surface=routing_input.surface,
                    selected_selector=selected_leaf.leaf_selector.normalized_selector,
                    target=resolved,
                    branch_history=branch_history,
                )
            return resolved
        return await self._execute_failover_chain(
            node=root,
            routing_input=routing_input,
            request=request,
            context=context,
            should_publish_diagnostics=should_publish,
        )

    async def _resolve_leaf(
        self,
        *,
        request: ChatRequest,
        context: RequestContext | None,
        leaf_node: CompositeLeafNode,
    ) -> BackendTarget:
        resolved = await self._leaf_target_resolver.resolve_leaf(
            request=request,
            context=context,
            leaf=leaf_node.leaf_selector,
        )
        if context is not None:
            context.extensions[COMPOSITE_SELECTED_LEAF_SELECTOR_KEY] = (
                leaf_node.leaf_selector.normalized_selector
            )
            context.extensions[COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY] = (
                leaf_node.leaf_selector.thinker_annotation
            )
        return resolved

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
        token_cache: dict[str, int] = {}
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
            if (
                self._should_suppress_thinker_selection(context)
                and current_branch.leaf_selector.thinker_annotation
            ):
                if should_publish_diagnostics:
                    branch_history_omitted = self._append_branch_history(
                        branch_history=branch_history,
                        entry=self._branch_history_entry(
                            selector_fragment=current_branch.leaf_selector.normalized_selector,
                            outcome_category=CompositeBranchOutcomeCategory.INELIGIBLE.value,
                            reason_code="interleaved_thinking_cooldown",
                        ),
                        limit=history_limit,
                        omitted=branch_history_omitted,
                    )
                state["next_index"] = branch_index + 1
                self._persist_state(context=context, state=state)
                branch_index += 1
                continue
            if not self._is_branch_eligible_for_max_context(
                leaf=current_branch,
                request_context_tokens=routing_input.request_context_tokens,
                request=request,
                token_cache=token_cache,
            ):
                if should_publish_diagnostics:
                    branch_history_omitted = self._append_branch_history(
                        branch_history=branch_history,
                        entry=self._branch_history_entry(
                            selector_fragment=current_branch.leaf_selector.normalized_selector,
                            outcome_category=CompositeBranchOutcomeCategory.INELIGIBLE.value,
                            reason_code="max_context_exceeded",
                        ),
                        limit=history_limit,
                        omitted=branch_history_omitted,
                    )
                state["next_index"] = branch_index + 1
                self._persist_state(context=context, state=state)
                branch_index += 1
                continue
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
    def _should_suppress_thinker_selection(context: RequestContext | None) -> bool:
        if context is None:
            return False
        return bool(
            context.extensions.get(INTERLEAVED_THINKING_SUPPRESS_THINKER_SELECTION_KEY)
        )

    @classmethod
    def _filter_thinker_children_if_needed(
        cls,
        *,
        context: RequestContext | None,
        children: Sequence[CompositeLeafNode],
    ) -> list[CompositeLeafNode]:
        if not cls._should_suppress_thinker_selection(context):
            return list(children)
        return [
            child for child in children if not child.leaf_selector.thinker_annotation
        ]

    @staticmethod
    def _has_thinker_branch(children: Sequence[CompositeLeafNode]) -> bool:
        return any(child.leaf_selector.thinker_annotation for child in children)

    @staticmethod
    def _select_interleaved_thinking_weighted_cycle_leaf(
        *,
        children: Sequence[CompositeLeafNode],
        selector: str,
        cycle_state: dict[str, JsonValue] | None,
        prefer_first: bool,
        context: RequestContext | None,
    ) -> CompositeLeafNode:
        sequence = CompositeRoutingCoordinator._build_interleaved_thinking_sequence(
            children
        )
        if not sequence:
            raise ValueError("Weighted node must contain at least one branch.")

        next_index = 0
        if isinstance(cycle_state, dict):
            stored_selector = cycle_state.get("selector")
            stored_sequence = cycle_state.get("sequence")
            stored_next_index = cycle_state.get("next_index")
            sequence_selectors = [
                child.leaf_selector.normalized_selector for child in sequence
            ]
            if (
                stored_selector == selector
                and isinstance(stored_sequence, list)
                and stored_sequence == sequence_selectors
                and isinstance(stored_next_index, int)
                and stored_next_index >= 0
            ):
                next_index = stored_next_index % len(sequence)
            elif prefer_first:
                next_index = (
                    CompositeRoutingCoordinator._first_annotation_sequence_index(
                        sequence
                    )
                    or 0
                )
        elif prefer_first:
            next_index = (
                CompositeRoutingCoordinator._first_annotation_sequence_index(sequence)
                or 0
            )

        selected_leaf = sequence[next_index]
        persisted_state: dict[str, JsonValue] = {
            "selector": selector,
            "sequence": [child.leaf_selector.normalized_selector for child in sequence],
            "next_index": (next_index + 1) % len(sequence),
        }
        if context is not None:
            context.extensions[INTERLEAVED_THINKING_WEIGHTED_CYCLE_STATE_KEY] = cast(
                JsonValue, persisted_state
            )
        return selected_leaf

    @staticmethod
    def _build_interleaved_thinking_sequence(
        children: Sequence[CompositeLeafNode],
    ) -> list[CompositeLeafNode]:
        non_thinkers: list[CompositeLeafNode] = []
        thinkers: list[CompositeLeafNode] = []
        for child in children:
            raw_weight = child.leaf_selector.weight_annotation
            resolved_weight = 1 if raw_weight is None else raw_weight
            if child.leaf_selector.thinker_annotation:
                thinkers.append(child)
            else:
                non_thinkers.extend([child] * resolved_weight)
        return [*non_thinkers, *thinkers]

    @staticmethod
    def _first_annotation_sequence_index(
        sequence: Sequence[CompositeLeafNode],
    ) -> int | None:
        for index, child in enumerate(sequence):
            if child.leaf_selector.first_annotation:
                return index
        return None

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
            details = error.details
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
            details = error.details
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
        eligible_leaves: Sequence[CompositeLeafNode],
        selected_leaf: CompositeLeafNode,
        configured_max_hops: int | None,
    ) -> None:
        if context is None:
            return
        persisted_branches: list[WeightedRetryBranch] = []
        for child in eligible_leaves:
            raw = child.leaf_selector.weight_annotation
            resolved_weight = 1 if raw is None else raw
            persisted_branches.append(
                {
                    "selector": child.leaf_selector.normalized_selector,
                    "weight": resolved_weight,
                }
            )
        max_hops = CompositeRoutingAttemptContext.resolve_max_hops(configured_max_hops)
        persisted: WeightedRetryRuntimeState = {
            "mode": WEIGHTED_RETRY_MODE,
            "branches": persisted_branches,
            "excluded_selectors": [],
            "selected_selector": selected_leaf.leaf_selector.normalized_selector,
            "hop_count": 0,
            "max_hops": max_hops,
        }
        context.extensions[COMPOSITE_ROUTING_STATE_KEY] = cast(JsonValue, persisted)

    @staticmethod
    def _is_branch_eligible_for_max_context(
        *,
        leaf: CompositeLeafNode,
        request_context_tokens: int | None,
        request: ChatRequest,
        token_cache: dict[str, int],
    ) -> bool:
        max_context_tokens = leaf.leaf_selector.max_context_tokens
        if max_context_tokens is None:
            return True
        resolved_request_tokens = (
            CompositeRoutingCoordinator._resolve_request_tokens_for_leaf(
                leaf=leaf,
                request_context_tokens=request_context_tokens,
                request=request,
                token_cache=token_cache,
            )
        )
        if resolved_request_tokens is None:
            return True
        return resolved_request_tokens <= max_context_tokens

    def _filter_children_by_max_context(
        self,
        *,
        children: Sequence[CompositeLeafNode],
        request_context_tokens: int | None,
        request: ChatRequest,
        token_cache: dict[str, int],
    ) -> tuple[list[CompositeLeafNode], list[dict[str, JsonValue]]]:
        eligible: list[CompositeLeafNode] = []
        ineligible_history: list[dict[str, JsonValue]] = []
        for child in children:
            if self._is_branch_eligible_for_max_context(
                leaf=child,
                request_context_tokens=request_context_tokens,
                request=request,
                token_cache=token_cache,
            ):
                eligible.append(child)
                continue
            ineligible_history.append(
                self._branch_history_entry(
                    selector_fragment=child.leaf_selector.normalized_selector,
                    outcome_category=CompositeBranchOutcomeCategory.INELIGIBLE.value,
                    reason_code="max_context_exceeded",
                )
            )
        return eligible, ineligible_history

    @staticmethod
    def _resolve_request_tokens_for_leaf(
        *,
        leaf: CompositeLeafNode,
        request_context_tokens: int | None,
        request: ChatRequest,
        token_cache: dict[str, int],
    ) -> int | None:
        if request_context_tokens is not None:
            return request_context_tokens

        model_hint = leaf.leaf_selector.model_name.strip()
        if not model_hint:
            model_hint = leaf.leaf_selector.normalized_selector

        cached_tokens = token_cache.get(model_hint)
        if cached_tokens is not None:
            return cached_tokens

        try:
            prompt_text = extract_prompt_text(request.messages)
            resolved_tokens = count_tokens(prompt_text, model=model_hint)
        except (TypeError, ValueError, AttributeError, KeyError):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to estimate request context tokens for max_context; branch remains eligible.",
                    exc_info=True,
                )
            return None

        token_cache[model_hint] = resolved_tokens
        return resolved_tokens

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
