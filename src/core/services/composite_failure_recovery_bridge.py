"""Runtime bridge from failure recovery to composite failover state."""

from __future__ import annotations

from typing import cast

from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.model_utils import parse_model_with_params
from src.core.domain.request_context import RequestContext
from src.core.services.composite_diagnostics_publisher import (
    CompositeDiagnosticsPublisher,
)
from src.core.services.composite_routing_state import (
    COMPOSITE_ROUTING_STATE_KEY,
    FAILOVER_MODE,
    FailoverRuntimeState,
    build_budget_exhausted_error,
    build_failover_exhausted_error,
    resolve_composite_routing_surface,
)

__all__ = ["CompositeFailureRecoveryBridge"]


class CompositeFailureRecoveryBridge:
    """Builds the next composite failover attempt when runtime conditions allow it."""

    def __init__(
        self,
        *,
        diagnostics_publisher: CompositeDiagnosticsPublisher | None = None,
    ) -> None:
        self._diagnostics_publisher = (
            diagnostics_publisher or CompositeDiagnosticsPublisher()
        )

    def build_next_request(
        self,
        *,
        request: CanonicalChatRequest,
        context: RequestContext | None,
        content_started: bool,
    ) -> CanonicalChatRequest | None:
        if context is None:
            return None
        if content_started or bool(context.extensions.get("meaningful_output_emitted")):
            return None

        state = self._load_state(context)
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
    def _load_state(context: RequestContext) -> FailoverRuntimeState | None:
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
