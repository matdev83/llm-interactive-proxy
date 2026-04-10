"""Runtime bridge from failure recovery to composite failover state."""

from __future__ import annotations

import asyncio
from typing import cast

from pydantic.types import JsonValue

from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    InvalidRequestError,
    LLMProxyError,
    ParsingError,
    RoutingError,
    SessionCancelledError,
    TranslationError,
    ValidationError,
)
from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.model_utils import parse_model_with_params
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
    resolve_composite_routing_surface,
)
from src.core.services.weighted_branch_selector import WeightedBranchSelector

__all__ = ["CompositeFailureRecoveryBridge"]


class CompositeFailureRecoveryBridge:
    """Builds the next composite failover attempt when runtime conditions allow it."""

    def __init__(
        self,
        *,
        diagnostics_publisher: CompositeDiagnosticsPublisher | None = None,
        weighted_branch_selector: WeightedBranchSelector | None = None,
    ) -> None:
        self._diagnostics_publisher = (
            diagnostics_publisher or CompositeDiagnosticsPublisher()
        )
        self._weighted_branch_selector = (
            weighted_branch_selector or WeightedBranchSelector()
        )

    def build_next_request(
        self,
        *,
        request: CanonicalChatRequest,
        context: RequestContext | None,
        content_started: bool,
        error: Exception | None = None,
    ) -> CanonicalChatRequest | None:
        if context is None:
            return None
        if content_started or bool(context.extensions.get("meaningful_output_emitted")):
            return None

        weighted = self._load_weighted_state(context)
        if weighted is not None:
            return self._build_weighted_retry_request(
                request=request,
                context=context,
                weighted=weighted,
                error=error,
            )

        state = self._load_failover_state(context)
        if state is None:
            return None
        if state["hop_count"] >= state["max_hops"]:
            self._publish_exhaustion(
                context=context,
                request=request,
                reason="attempt_budget_exhausted",
                details={
                    "hop_count": state["hop_count"],
                    "max_hops": state["max_hops"],
                },
            )
            raise build_budget_exhausted_error(state)
        if state["next_index"] >= len(state["branches"]):
            self._publish_exhaustion(
                context=context,
                request=request,
                reason="failover_exhausted",
                details={
                    "next_index": state["next_index"],
                    "branch_count": len(state["branches"]),
                },
            )
            raise build_failover_exhausted_error(state)

        selector = state["branches"][state["next_index"]]
        parsed = parse_model_with_params(selector, default_backend="")
        extra_body = dict(request.extra_body or {})
        extra_body["_resolved_uri_params"] = dict(parsed.uri_params)
        if parsed.backend_type:
            extra_body["backend_type"] = parsed.backend_type
        else:
            extra_body.pop("backend_type", None)

        state["next_index"] += 1
        state["hop_count"] += 1
        context.extensions[COMPOSITE_ROUTING_STATE_KEY] = {
            "mode": FAILOVER_MODE,
            "branches": list(state["branches"]),
            "next_index": state["next_index"],
            "hop_count": state["hop_count"],
            "max_hops": state["max_hops"],
        }
        return request.model_copy(
            update={
                "model": selector,
                "extra_body": extra_body,
            }
        )

    def _build_weighted_retry_request(
        self,
        *,
        request: CanonicalChatRequest,
        context: RequestContext,
        weighted: WeightedRetryRuntimeState,
        error: Exception | None,
    ) -> CanonicalChatRequest | None:
        if error is None or not self._is_weighted_reroll_eligible(error):
            return None

        hop_count = weighted["hop_count"]
        max_hops = weighted["max_hops"]
        if hop_count >= max_hops:
            budget_state: FailoverRuntimeState = {
                "mode": FAILOVER_MODE,
                "branches": [],
                "next_index": 0,
                "hop_count": hop_count,
                "max_hops": max_hops,
            }
            self._publish_exhaustion(
                context=context,
                request=request,
                reason="attempt_budget_exhausted",
                details={
                    "hop_count": hop_count,
                    "max_hops": max_hops,
                },
            )
            raise build_budget_exhausted_error(budget_state)

        selected = weighted["selected_selector"]
        excluded = list(weighted["excluded_selectors"])
        if selected not in excluded:
            excluded.append(selected)

        remaining: list[WeightedRetryBranch] = []
        excluded_set = set(excluded)
        for item in weighted["branches"]:
            selector = item["selector"]
            if selector not in excluded_set:
                remaining.append(item)

        if not remaining:
            weighted["excluded_selectors"] = excluded
            context.extensions[COMPOSITE_ROUTING_STATE_KEY] = cast(
                JsonValue, self._serialize_weighted_state(weighted)
            )
            return None

        if len(remaining) == 1:
            next_selector = remaining[0]["selector"]
        else:
            weights = [branch["weight"] for branch in remaining]
            selected_index = self._weighted_branch_selector.select_index_from_weights(
                weights
            )
            next_selector = remaining[selected_index]["selector"]

        hop_count += 1
        weighted["excluded_selectors"] = excluded
        weighted["selected_selector"] = next_selector
        weighted["hop_count"] = hop_count
        context.extensions[COMPOSITE_ROUTING_STATE_KEY] = cast(
            JsonValue, self._serialize_weighted_state(weighted)
        )

        parsed = parse_model_with_params(next_selector, default_backend="")
        extra_body = dict(request.extra_body or {})
        extra_body["_resolved_uri_params"] = dict(parsed.uri_params)
        if parsed.backend_type:
            extra_body["backend_type"] = parsed.backend_type
        else:
            extra_body.pop("backend_type", None)

        return request.model_copy(
            update={
                "model": next_selector,
                "extra_body": extra_body,
            }
        )

    @staticmethod
    def _serialize_weighted_state(
        weighted: WeightedRetryRuntimeState,
    ) -> WeightedRetryRuntimeState:
        return {
            "mode": WEIGHTED_RETRY_MODE,
            "branches": list(weighted["branches"]),
            "excluded_selectors": list(weighted["excluded_selectors"]),
            "selected_selector": weighted["selected_selector"],
            "hop_count": weighted["hop_count"],
            "max_hops": weighted["max_hops"],
        }

    @staticmethod
    def _is_weighted_reroll_eligible(exc: Exception) -> bool:
        if isinstance(exc, asyncio.CancelledError):
            return False
        if isinstance(
            exc,
            AuthenticationError
            | SessionCancelledError
            | ConfigurationError
            | ValidationError
            | InvalidRequestError
            | RoutingError
            | TranslationError
            | ParsingError,
        ):
            return False
        if isinstance(exc, BackendError):
            status_code = getattr(exc, "status_code", None)
            if status_code in {401, 403, 499}:
                return False
            details = exc.details if isinstance(exc.details, dict) else {}
            error_code = getattr(exc, "code", None)
            if not isinstance(error_code, str) or not error_code:
                candidate = details.get("code")
                if isinstance(candidate, str):
                    error_code = candidate
            return not (
                isinstance(error_code, str)
                and error_code
                in {
                    "invalid_api_key",
                    "authentication_failed",
                    "unauthorized",
                    "forbidden",
                }
            )
        if isinstance(exc, LLMProxyError):
            return False
        return False

    def _publish_exhaustion(
        self,
        *,
        context: RequestContext,
        request: CanonicalChatRequest,
        reason: str,
        details: dict[str, int],
    ) -> None:
        surface = resolve_composite_routing_surface(context)
        self._diagnostics_publisher.publish_exhaustion(
            context=context,
            selector=request.model,
            surface=surface,
            reason=reason,
            details=details,
        )

    @staticmethod
    def _load_failover_state(context: RequestContext) -> FailoverRuntimeState | None:
        raw_state = context.extensions.get(COMPOSITE_ROUTING_STATE_KEY)
        if not isinstance(raw_state, dict):
            return None

        mode = raw_state.get("mode")
        branches = raw_state.get("branches")
        next_index = raw_state.get("next_index")
        hop_count = raw_state.get("hop_count")
        max_hops = raw_state.get("max_hops")

        if (
            mode != FAILOVER_MODE
            or not isinstance(branches, list)
            or not all(isinstance(item, str) for item in branches)
            or not isinstance(next_index, int)
            or not isinstance(hop_count, int)
            or not isinstance(max_hops, int)
            or next_index < 0
            or hop_count < 0
            or max_hops <= 0
        ):
            return None

        return {
            "mode": FAILOVER_MODE,
            "branches": cast(list[str], branches),
            "next_index": next_index,
            "hop_count": hop_count,
            "max_hops": max_hops,
        }

    @staticmethod
    def _load_weighted_state(
        context: RequestContext,
    ) -> WeightedRetryRuntimeState | None:
        raw_state = context.extensions.get(COMPOSITE_ROUTING_STATE_KEY)
        if not isinstance(raw_state, dict):
            return None
        if raw_state.get("mode") != WEIGHTED_RETRY_MODE:
            return None
        branches = raw_state.get("branches")
        excluded = raw_state.get("excluded_selectors")
        selected = raw_state.get("selected_selector")
        hop_count = raw_state.get("hop_count")
        max_hops = raw_state.get("max_hops")
        if (
            not isinstance(branches, list)
            or not isinstance(excluded, list)
            or not all(isinstance(x, str) for x in excluded)
            or not isinstance(selected, str)
            or not selected.strip()
            or not isinstance(hop_count, int)
            or not isinstance(max_hops, int)
            or hop_count < 0
            or max_hops <= 0
        ):
            return None
        if not branches:
            return None

        normalized_excluded = cast(list[str], excluded)
        normalized_branches: list[WeightedRetryBranch] = []
        known_selectors: list[str] = []
        for branch in branches:
            if not isinstance(branch, dict):
                return None
            selector = branch.get("selector")
            weight = branch.get("weight")
            if (
                not isinstance(selector, str)
                or not selector.strip()
                or not isinstance(weight, int)
                or weight <= 0
            ):
                return None
            normalized_selector = selector.strip()
            normalized_branches.append(
                {"selector": normalized_selector, "weight": weight}
            )
            known_selectors.append(normalized_selector)
        if selected not in known_selectors:
            return None

        return {
            "mode": WEIGHTED_RETRY_MODE,
            "branches": normalized_branches,
            "excluded_selectors": list(normalized_excluded),
            "selected_selector": selected,
            "hop_count": hop_count,
            "max_hops": max_hops,
        }
