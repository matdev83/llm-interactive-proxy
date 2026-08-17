from __future__ import annotations

import logging
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
from src.core.services.composite_routing_state import (
    COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY,
    COMPOSITE_SELECTED_LEAF_SELECTOR_KEY,
    INTERLEAVED_THINKING_SUPPRESS_THINKER_SELECTION_KEY,
    INTERLEAVED_THINKING_WEIGHTED_CYCLE_STATE_KEY,
)
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
async def test_weighted_coordinator_persists_selected_thinker_metadata() -> None:
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector="[thinker]openai:gpt-4^[weight=1]anthropic:claude-3-5-sonnet",
        surface=RoutingSurface.MAIN,
        interleaved_thinking_weighted_cycle_state={
            "selector": (
                "[weight=1][thinker]openai:gpt-4^"
                "[weight=1]anthropic:claude-3-5-sonnet"
            ),
            "sequence": ["anthropic:claude-3-5-sonnet", "openai:gpt-4"],
            "next_index": 1,
        },
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

    await coordinator.execute(
        plan=plan,
        routing_input=routing_input,
        request=_request(),
        context=context,
    )

    assert context.extensions[COMPOSITE_SELECTED_LEAF_SELECTOR_KEY] == "openai:gpt-4"
    assert context.extensions[COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY] is True


@pytest.mark.asyncio
async def test_weighted_coordinator_persists_non_thinker_metadata() -> None:
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector="[thinker]openai:gpt-4^[weight=10]anthropic:claude-3-5-sonnet",
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
            random_value_provider=lambda: 0.99
        ),
        leaf_target_resolver=leaf_resolver,
    )
    context = _context()

    await coordinator.execute(
        plan=plan,
        routing_input=routing_input,
        request=_request(),
        context=context,
    )

    assert (
        context.extensions[COMPOSITE_SELECTED_LEAF_SELECTOR_KEY]
        == "anthropic:claude-3-5-sonnet"
    )
    assert context.extensions[COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY] is False


@pytest.mark.asyncio
async def test_weighted_coordinator_with_thinker_cycles_non_thinkers_then_thinker() -> (
    None
):
    parser = CompositeSelectorParser()
    selector = (
        "[thinker]openai:gpt-5.5?"
        "reasoning_effort=low^"
        "[weight=2]opencode-go:opencode-go/mimo-v2.5-pro?"
        "reasoning_effort=high^"
        "[weight=1]opencode-go:opencode-go/deepseek-v4-flash?"
        "reasoning_effort=max"
    )
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:gpt-5.5?reasoning_effort=low": _LeafOutcome(
                target=_target("openai", "gpt-5.5")
            ),
            "opencode-go:opencode-go/mimo-v2.5-pro?reasoning_effort=high": _LeafOutcome(
                target=_target("opencode-go", "opencode-go/mimo-v2.5-pro")
            ),
            "opencode-go:opencode-go/deepseek-v4-flash?reasoning_effort=max": _LeafOutcome(
                target=_target("opencode-go", "opencode-go/deepseek-v4-flash")
            ),
        }
    )

    def random_value_provider() -> float:
        raise AssertionError("thinker-weighted routing must not use random selection")

    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=random_value_provider
        ),
        leaf_target_resolver=leaf_resolver,
    )
    cycle_state: dict[str, Any] | None = None
    selected: list[str] = []
    thinker_flags: list[bool] = []

    for _ in range(4):
        routing_input = CompositeRoutingInput(
            selector=selector,
            surface=RoutingSurface.MAIN,
            interleaved_thinking_weighted_cycle_state=cycle_state,
        )
        plan = parser.parse(routing_input)
        context = _context()

        await coordinator.execute(
            plan=plan,
            routing_input=routing_input,
            request=_request(),
            context=context,
        )

        selected.append(
            cast(str, context.extensions[COMPOSITE_SELECTED_LEAF_SELECTOR_KEY])
        )
        thinker_flags.append(
            cast(bool, context.extensions[COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY])
        )
        cycle_state = cast(
            dict[str, Any],
            context.extensions[INTERLEAVED_THINKING_WEIGHTED_CYCLE_STATE_KEY],
        )

    assert selected == [
        "opencode-go:opencode-go/mimo-v2.5-pro?reasoning_effort=high",
        "opencode-go:opencode-go/mimo-v2.5-pro?reasoning_effort=high",
        "opencode-go:opencode-go/deepseek-v4-flash?reasoning_effort=max",
        "openai:gpt-5.5?reasoning_effort=low",
    ]
    assert thinker_flags == [False, False, False, True]


@pytest.mark.asyncio
async def test_weighted_coordinator_with_thinker_restarts_cycle_after_thinker() -> None:
    parser = CompositeSelectorParser()
    selector = "[thinker]openai:gpt-4^[weight=1]anthropic:claude"
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:gpt-4": _LeafOutcome(target=_target("openai", "gpt-4")),
            "anthropic:claude": _LeafOutcome(target=_target("anthropic", "claude")),
        }
    )
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.0
        ),
        leaf_target_resolver=leaf_resolver,
    )
    cycle_state: dict[str, Any] | None = None
    selected: list[str] = []

    for _ in range(3):
        routing_input = CompositeRoutingInput(
            selector=selector,
            surface=RoutingSurface.MAIN,
            interleaved_thinking_weighted_cycle_state=cycle_state,
        )
        context = _context()
        await coordinator.execute(
            plan=parser.parse(routing_input),
            routing_input=routing_input,
            request=_request(),
            context=context,
        )
        selected.append(
            cast(str, context.extensions[COMPOSITE_SELECTED_LEAF_SELECTOR_KEY])
        )
        cycle_state = cast(
            dict[str, Any],
            context.extensions[INTERLEAVED_THINKING_WEIGHTED_CYCLE_STATE_KEY],
        )

    assert selected == ["anthropic:claude", "openai:gpt-4", "anthropic:claude"]


@pytest.mark.asyncio
async def test_weighted_coordinator_with_thinker_preserves_first_annotation() -> None:
    parser = CompositeSelectorParser()
    selector = "openai:regular^[first]openai:first^[thinker]openai:thinker"
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:regular": _LeafOutcome(target=_target("openai", "regular")),
            "openai:first": _LeafOutcome(target=_target("openai", "first")),
            "openai:thinker": _LeafOutcome(target=_target("openai", "thinker")),
        }
    )
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.0
        ),
        leaf_target_resolver=leaf_resolver,
    )
    routing_input = CompositeRoutingInput(
        selector=selector,
        surface=RoutingSurface.MAIN,
        prefer_first_weighted_branch=True,
    )
    context = _context()

    await coordinator.execute(
        plan=parser.parse(routing_input),
        routing_input=routing_input,
        request=_request(),
        context=context,
    )

    assert context.extensions[COMPOSITE_SELECTED_LEAF_SELECTOR_KEY] == "openai:first"
    cycle_state = cast(
        dict[str, Any],
        context.extensions[INTERLEAVED_THINKING_WEIGHTED_CYCLE_STATE_KEY],
    )
    assert cycle_state["next_index"] == 2


@pytest.mark.asyncio
async def test_weighted_coordinator_with_thinker_uses_one_thinker_slot_per_cycle() -> (
    None
):
    parser = CompositeSelectorParser()
    selector = "[weight=3,thinker]openai:thinker^[weight=1]openai:regular"
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:thinker": _LeafOutcome(target=_target("openai", "thinker")),
            "openai:regular": _LeafOutcome(target=_target("openai", "regular")),
        }
    )
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.0
        ),
        leaf_target_resolver=leaf_resolver,
    )
    cycle_state: dict[str, Any] | None = None
    selected: list[str] = []

    for _ in range(3):
        routing_input = CompositeRoutingInput(
            selector=selector,
            surface=RoutingSurface.MAIN,
            interleaved_thinking_weighted_cycle_state=cycle_state,
        )
        context = _context()
        await coordinator.execute(
            plan=parser.parse(routing_input),
            routing_input=routing_input,
            request=_request(),
            context=context,
        )
        selected.append(
            cast(str, context.extensions[COMPOSITE_SELECTED_LEAF_SELECTOR_KEY])
        )
        cycle_state = cast(
            dict[str, Any],
            context.extensions[INTERLEAVED_THINKING_WEIGHTED_CYCLE_STATE_KEY],
        )

    assert selected == ["openai:regular", "openai:thinker", "openai:regular"]


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
async def test_weighted_coordinator_skips_thinker_when_suppressed() -> None:
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector="[weight=100,thinker]openai:gpt-4^[weight=1]anthropic:claude-3-5-sonnet",
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
    context.extensions[INTERLEAVED_THINKING_SUPPRESS_THINKER_SELECTION_KEY] = True

    result = await coordinator.execute(
        plan=plan,
        routing_input=routing_input,
        request=_request(),
        context=context,
    )

    assert result.backend == "anthropic"
    assert leaf_resolver.calls == ["anthropic:claude-3-5-sonnet"]
    assert context.extensions[COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY] is False


@pytest.mark.asyncio
async def test_weighted_coordinator_raises_when_suppression_leaves_only_thinker() -> (
    None
):
    parser = CompositeSelectorParser()
    routing_input = CompositeRoutingInput(
        selector=(
            "[weight=100,thinker]openai:gpt-4^"
            "[weight=1,max_context=10]anthropic:claude-3-5-sonnet"
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
    context.extensions[INTERLEAVED_THINKING_SUPPRESS_THINKER_SELECTION_KEY] = True

    with pytest.raises(RoutingError) as exc_info:
        await coordinator.execute(
            plan=plan,
            routing_input=routing_input,
            request=_request(),
            context=context,
        )

    assert exc_info.value.details.get("reason") == "interleaved_thinking_suppressed"
    assert leaf_resolver.calls == []


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


@pytest.mark.asyncio
async def test_interleaved_thinking_turn_selection_logs_cycle_position(
    caplog: pytest.LogCaptureFixture,
) -> None:
    parser = CompositeSelectorParser()
    selector = "[thinker]openai:gpt-4^[weight=2]openrouter:deepseek"
    routing_input = CompositeRoutingInput(
        selector=selector,
        surface=RoutingSurface.MAIN,
    )
    plan = parser.parse(routing_input)
    leaf_resolver = _LeafResolverDouble(
        outcomes={
            "openai:gpt-4": _LeafOutcome(target=_target("openai", "gpt-4")),
            "openrouter:deepseek": _LeafOutcome(
                target=_target("openrouter", "deepseek")
            ),
        }
    )
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.0
        ),
        leaf_target_resolver=leaf_resolver,
    )

    with caplog.at_level(
        logging.INFO,
        logger="src.core.services.composite_routing_coordinator",
    ):
        context = _context()
        await coordinator.execute(
            plan=plan,
            routing_input=routing_input,
            request=_request(),
            context=context,
        )

    assert any(
        "Interleaved thinking turn selected:" in record.message
        and "role=executor" in record.message
        and "cycle_index=1/3" in record.message
        for record in caplog.records
    )
