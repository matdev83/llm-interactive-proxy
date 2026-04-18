from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest
from src.core.common.exceptions import ConfigurationError, RoutingError, ValidationError
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.composite_routing import (
    CompositeLeafSelector,
    CompositeRoutingInput,
    RoutingSurface,
)
from src.core.domain.request_context import RequestContext
from src.core.services.composite_routing_coordinator import CompositeRoutingCoordinator
from src.core.services.composite_selector_parser import CompositeSelectorParser
from src.core.services.weighted_branch_selector import WeightedBranchSelector


@dataclass
class _LeafOutcome:
    target: BackendTarget | None = None
    error: Exception | None = None


class _LeafResolverDouble:
    def __init__(self, outcomes: dict[str, _LeafOutcome]) -> None:
        self._outcomes = outcomes
        self.calls: list[str] = []

    async def resolve_leaf(
        self,
        *,
        request: ChatRequest,
        context: RequestContext | None,
        leaf: CompositeLeafSelector,
    ) -> BackendTarget:
        _ = request
        _ = context
        leaf_selector = leaf.normalized_selector
        self.calls.append(leaf_selector)
        outcome = self._outcomes[leaf_selector]
        if outcome.error is not None:
            raise outcome.error
        assert outcome.target is not None
        return outcome.target


def _request() -> ChatRequest:
    return ChatRequest(
        model="unused",
        messages=[ChatMessage(role="user", content="hello")],
    )


def _context() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="req-composite-coordinator",
        session_id="session-composite-coordinator",
    )


def _target(backend: str, model: str) -> BackendTarget:
    return BackendTarget(backend=backend, model=model, uri_params={})


@pytest.mark.asyncio
async def test_weighted_coordinator_selects_exactly_one_branch() -> None:
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector="[weight=3]openai:gpt-4^anthropic:claude-3-5-sonnet",
        surface=RoutingSurface.MAIN,
    )
    plan = parser.parse(routing_input)
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:gpt-4": _LeafOutcome(target=_target("openai", "gpt-4")),
            "anthropic:claude-3-5-sonnet": _LeafOutcome(
                target=_target("anthropic", "claude-3-5-sonnet")
            ),
        }
    )
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.0
        ),
        leaf_target_resolver=leaf_resolver,
    )
    context = _context()

    result = await coordinator.execute(
        plan=plan,
        routing_input=routing_input,
        request=_request(),
        context=context,
    )

    assert result.backend == "openai"
    assert result.model == "gpt-4"
    assert leaf_resolver.calls == ["openai:gpt-4"]
    state = cast(dict[str, Any], context.extensions["composite_routing_state"])
    assert state["mode"] == "weighted_retry"
    assert state["selected_selector"] == "openai:gpt-4"
    assert state["excluded_selectors"] == []
    assert state["hop_count"] == 0
    assert state["max_hops"] > 0
    branches = state["branches"]
    assert isinstance(branches, list)
    assert branches == [
        {"selector": "openai:gpt-4", "weight": 3},
        {"selector": "anthropic:claude-3-5-sonnet", "weight": 1},
    ]
    diagnostics = context.extensions.get("composite_routing_diagnostics")
    assert isinstance(diagnostics, dict)
    branch_history = diagnostics.get("branch_history")
    assert isinstance(branch_history, list)
    assert any(
        isinstance(entry, dict) and entry.get("outcome_category") == "selected"
        for entry in branch_history
    )
    assert any(
        isinstance(entry, dict)
        and entry.get("outcome_category") == "not_selected"
        and entry.get("reason_code") == "weighted_random_non_winner"
        for entry in branch_history
    )


@pytest.mark.asyncio
async def test_failover_coordinator_advances_with_shared_hop_budget() -> None:
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector="openai:gpt-4|anthropic:claude-3-5-sonnet|gemini:gemini-2.0-flash",
        surface=RoutingSurface.AUXILIARY,
        configured_max_hops=2,
    )
    plan = parser.parse(routing_input)
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:gpt-4": _LeafOutcome(
                error=RoutingError(
                    message="primary unavailable",
                    details={"code": "temporarily_unavailable"},
                )
            ),
            "anthropic:claude-3-5-sonnet": _LeafOutcome(
                error=RoutingError(
                    message="secondary unavailable",
                    details={"code": "temporarily_unavailable"},
                )
            ),
            "gemini:gemini-2.0-flash": _LeafOutcome(
                target=_target("gemini", "gemini-2.0-flash")
            ),
        }
    )
    context = _context()
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.5
        ),
        leaf_target_resolver=leaf_resolver,
    )

    result = await coordinator.execute(
        plan=plan,
        routing_input=routing_input,
        request=_request(),
        context=context,
    )

    assert result.backend == "gemini"
    assert result.model == "gemini-2.0-flash"
    state = cast(dict[str, Any], context.extensions["composite_routing_state"])
    assert state["mode"] == "failover"
    assert state["next_index"] == 3
    assert state["hop_count"] == 2
    diagnostics = context.extensions.get("composite_routing_diagnostics")
    assert isinstance(diagnostics, dict)
    assert diagnostics.get("surface") == "auxiliary"
    selected_target = diagnostics.get("selected_target")
    assert isinstance(selected_target, dict)
    assert selected_target.get("backend") == "gemini"
    assert selected_target.get("model") == "gemini-2.0-flash"
    branch_history = diagnostics.get("branch_history")
    assert isinstance(branch_history, list)
    assert len(branch_history) == 3
    assert any(
        isinstance(entry, dict) and entry.get("outcome_category") == "selected"
        for entry in branch_history
    )
    assert any(
        isinstance(entry, dict)
        and entry.get("outcome_category") == "ineligible"
        and entry.get("reason_code") == "temporarily_unavailable"
        for entry in branch_history
    )


@pytest.mark.asyncio
async def test_failover_coordinator_returns_deterministic_exhaustion_when_hops_exceeded() -> (
    None
):
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector="openai:gpt-4|anthropic:claude-3-5-sonnet",
        surface=RoutingSurface.QUALITY_VERIFIER,
        configured_max_hops=1,
    )
    plan = parser.parse(routing_input)
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:gpt-4": _LeafOutcome(
                error=RoutingError(
                    message="primary unavailable",
                    details={"code": "temporarily_unavailable"},
                )
            ),
            "anthropic:claude-3-5-sonnet": _LeafOutcome(
                error=RoutingError(
                    message="secondary unavailable",
                    details={"code": "temporarily_unavailable"},
                )
            ),
        }
    )
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.0
        ),
        leaf_target_resolver=leaf_resolver,
    )

    context = _context()
    with pytest.raises(RoutingError) as exc_info:
        await coordinator.execute(
            plan=plan,
            routing_input=routing_input,
            request=_request(),
            context=context,
        )

    assert exc_info.value.details["reason"] == "attempt_budget_exhausted"
    diagnostics = context.extensions.get("composite_routing_diagnostics")
    assert isinstance(diagnostics, dict)
    exhaustion = diagnostics.get("exhaustion")
    assert isinstance(exhaustion, dict)
    assert exhaustion.get("reason") == "attempt_budget_exhausted"
    assert exhaustion.get("max_hops") == 1


@pytest.mark.asyncio
async def test_failover_coordinator_does_not_advance_on_unexpected_leaf_errors() -> (
    None
):
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector="openai:gpt-4|anthropic:claude-3-5-sonnet",
        surface=RoutingSurface.MAIN,
        configured_max_hops=5,
    )
    plan = parser.parse(routing_input)
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:gpt-4": _LeafOutcome(error=RuntimeError("resolver bug")),
            "anthropic:claude-3-5-sonnet": _LeafOutcome(
                target=_target("anthropic", "claude-3-5-sonnet")
            ),
        }
    )
    context = _context()
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.0
        ),
        leaf_target_resolver=leaf_resolver,
    )

    with pytest.raises(RuntimeError, match="resolver bug"):
        await coordinator.execute(
            plan=plan,
            routing_input=routing_input,
            request=_request(),
            context=context,
        )

    assert leaf_resolver.calls == ["openai:gpt-4"]
    state = context.extensions.get("composite_routing_state")
    assert isinstance(state, dict)
    assert state.get("next_index") == 0
    assert state.get("hop_count") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        RoutingError(
            message="nope",
            details={"code": "temporarily_unavailable"},
        ),
        ValidationError(message="bad", details={}),
        ConfigurationError(message="misconfigured", details={}),
    ],
)
async def test_failover_coordinator_advances_for_routing_validation_configuration_errors(
    error: Exception,
) -> None:
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector="openai:gpt-4|anthropic:claude-3-5-sonnet",
        surface=RoutingSurface.MAIN,
        configured_max_hops=5,
    )
    plan = parser.parse(routing_input)
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:gpt-4": _LeafOutcome(error=error),
            "anthropic:claude-3-5-sonnet": _LeafOutcome(
                target=_target("anthropic", "claude-3-5-sonnet")
            ),
        }
    )
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.0
        ),
        leaf_target_resolver=leaf_resolver,
    )

    result = await coordinator.execute(
        plan=plan,
        routing_input=routing_input,
        request=_request(),
        context=_context(),
    )

    assert result.backend == "anthropic"
    assert leaf_resolver.calls == ["openai:gpt-4", "anthropic:claude-3-5-sonnet"]


@pytest.mark.asyncio
async def test_weighted_coordinator_uses_first_branch_when_prefer_first_true() -> None:
    """Coordinator with prefer_first_weighted_branch=True selects the first-tagged branch."""
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector="[first]openai:gpt-4^[weight=100]anthropic:claude-3-5-sonnet",
        surface=RoutingSurface.MAIN,
        prefer_first_weighted_branch=True,
    )
    plan = parser.parse(routing_input)
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:gpt-4": _LeafOutcome(target=_target("openai", "gpt-4")),
            "anthropic:claude-3-5-sonnet": _LeafOutcome(
                target=_target("anthropic", "claude-3-5-sonnet")
            ),
        }
    )
    # Even with RNG that would pick claude (weight=100), prefer_first should pick gpt-4
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.99
        ),
        leaf_target_resolver=leaf_resolver,
    )
    context = _context()

    result = await coordinator.execute(
        plan=plan,
        routing_input=routing_input,
        request=_request(),
        context=context,
    )

    assert result.backend == "openai"
    assert result.model == "gpt-4"
    assert leaf_resolver.calls == ["openai:gpt-4"]


@pytest.mark.asyncio
async def test_weighted_coordinator_uses_weighted_random_when_prefer_first_false() -> (
    None
):
    """Coordinator with prefer_first_weighted_branch=False uses weighted selection."""
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector="[first]openai:gpt-4^[weight=100]anthropic:claude-3-5-sonnet",
        surface=RoutingSurface.MAIN,
        prefer_first_weighted_branch=False,
    )
    plan = parser.parse(routing_input)
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:gpt-4": _LeafOutcome(target=_target("openai", "gpt-4")),
            "anthropic:claude-3-5-sonnet": _LeafOutcome(
                target=_target("anthropic", "claude-3-5-sonnet")
            ),
        }
    )
    # RNG=0.99 with total=101: threshold=99.99 -> openai=1, claude=101 -> picks claude
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.99
        ),
        leaf_target_resolver=leaf_resolver,
    )
    context = _context()

    result = await coordinator.execute(
        plan=plan,
        routing_input=routing_input,
        request=_request(),
        context=context,
    )

    # Should use weighted selection, picking the high-weight claude
    assert result.backend == "anthropic"
    assert result.model == "claude-3-5-sonnet"


@pytest.mark.asyncio
async def test_weighted_coordinator_retry_does_not_use_first_tag() -> None:
    """On weighted retry (bridge), first annotation is ignored — uses weighted random."""
    from src.core.services.composite_failure_recovery_bridge import (
        CompositeFailureRecoveryBridge,
    )
    from src.core.services.composite_routing_state import (
        COMPOSITE_ROUTING_STATE_KEY,
        WEIGHTED_RETRY_MODE,
    )

    bridge = CompositeFailureRecoveryBridge(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.99
        )
    )
    context = _context()
    context.extensions[COMPOSITE_ROUTING_STATE_KEY] = {
        "mode": WEIGHTED_RETRY_MODE,
        "branches": [
            {"selector": "openai:gpt-4", "weight": 1},
            {"selector": "anthropic:claude-3-5-sonnet", "weight": 100},
        ],
        "excluded_selectors": ["openai:gpt-4"],
        "selected_selector": "openai:gpt-4",
        "hop_count": 0,
        "max_hops": 3,
    }

    # Retry after a backend error — should use weighted selection among remaining
    from src.core.common.exceptions import BackendError

    next_request = bridge.build_next_request(
        request=cast(
            Any,
            ChatRequest(
                model="openai:gpt-4",
                messages=[ChatMessage(role="user", content="hello")],
                extra_body={
                    "backend_type": "openai",
                    "_resolved_uri_params": {},
                },
            ),
        ),
        context=context,
        content_started=False,
        error=BackendError("backend down", "openai", status_code=503),
    )

    # Should pick claude (weight=100) via weighted selection, not [first] tag
    assert next_request is not None
    assert next_request.model == "anthropic:claude-3-5-sonnet"
    state = cast(dict[str, Any], context.extensions[COMPOSITE_ROUTING_STATE_KEY])
    assert state["selected_selector"] == "anthropic:claude-3-5-sonnet"
    assert state["hop_count"] == 1


@pytest.mark.asyncio
async def test_weighted_coordinator_excludes_branches_over_max_context() -> None:
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector=(
            "[weight=10,max_context=10]openai:gpt-4^"
            "[weight=1,max_context=1000]anthropic:claude-3-5-sonnet"
        ),
        surface=RoutingSurface.MAIN,
        request_context_tokens=100,
    )
    plan = parser.parse(routing_input)
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:gpt-4": _LeafOutcome(target=_target("openai", "gpt-4")),
            "anthropic:claude-3-5-sonnet": _LeafOutcome(
                target=_target("anthropic", "claude-3-5-sonnet")
            ),
        }
    )
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.0
        ),
        leaf_target_resolver=leaf_resolver,
    )
    context = _context()

    result = await coordinator.execute(
        plan=plan,
        routing_input=routing_input,
        request=_request(),
        context=context,
    )

    assert result.backend == "anthropic"
    assert leaf_resolver.calls == ["anthropic:claude-3-5-sonnet"]
    diagnostics = context.extensions.get("composite_routing_diagnostics")
    assert isinstance(diagnostics, dict)
    branch_history = diagnostics.get("branch_history")
    assert isinstance(branch_history, list)
    assert any(
        isinstance(entry, dict)
        and entry.get("selector_fragment") == "openai:gpt-4"
        and entry.get("outcome_category") == "ineligible"
        and entry.get("reason_code") == "max_context_exceeded"
        for entry in branch_history
    )


@pytest.mark.asyncio
async def test_weighted_coordinator_raises_when_all_branches_exceed_max_context() -> (
    None
):
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector="[max_context=10]openai:gpt-4^[max_context=20]anthropic:claude-3-5-sonnet",
        surface=RoutingSurface.MAIN,
        request_context_tokens=100,
    )
    plan = parser.parse(routing_input)
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:gpt-4": _LeafOutcome(target=_target("openai", "gpt-4")),
            "anthropic:claude-3-5-sonnet": _LeafOutcome(
                target=_target("anthropic", "claude-3-5-sonnet")
            ),
        }
    )
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.0
        ),
        leaf_target_resolver=leaf_resolver,
    )
    context = _context()

    with pytest.raises(RoutingError) as exc_info:
        await coordinator.execute(
            plan=plan,
            routing_input=routing_input,
            request=_request(),
            context=context,
        )

    assert exc_info.value.details.get("reason") == "max_context_exhausted"
    assert leaf_resolver.calls == []


@pytest.mark.asyncio
async def test_single_leaf_selector_respects_max_context() -> None:
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector="[max_context=10]openai:gpt-4",
        surface=RoutingSurface.MAIN,
        request_context_tokens=100,
    )
    plan = parser.parse(routing_input)
    leaf_resolver = _LeafResolverDouble(
        outcomes={"openai:gpt-4": _LeafOutcome(target=_target("openai", "gpt-4"))}
    )
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.0
        ),
        leaf_target_resolver=leaf_resolver,
    )

    with pytest.raises(RoutingError) as exc_info:
        await coordinator.execute(
            plan=plan,
            routing_input=routing_input,
            request=_request(),
            context=_context(),
        )

    assert exc_info.value.details.get("reason") == "max_context_exceeded"
    assert leaf_resolver.calls == []
