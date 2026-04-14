from __future__ import annotations

from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.common.exceptions import RoutingError, ValidationError
from src.core.config.app_config import AppConfig
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.composite_routing import CompositeSelectorValidationError
from src.core.domain.request_context import RequestContext
from src.core.domain.session import Session, SessionState
from src.core.services.backend_model_resolver import BackendModelResolver
from src.core.services.composite_diagnostics_publisher import (
    CompositeDiagnosticsPublisher,
)
from src.core.services.composite_leaf_target_resolver_adapter import (
    CompositeLeafTargetResolverAdapter,
)
from src.core.services.composite_routing_coordinator import CompositeRoutingCoordinator
from src.core.services.composite_routing_service import CompositeRoutingService
from src.core.services.composite_routing_state import (
    COMPOSITE_LEAF_RESOLUTION_EXTRA_BODY_KEY,
    COMPOSITE_LEAF_SELECTOR_EXTRA_BODY_KEY,
)
from src.core.services.composite_selector_parser import CompositeSelectorParser
from src.core.services.weighted_branch_selector import WeightedBranchSelector


def _request(model: str) -> ChatRequest:
    return ChatRequest(
        model=model,
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={},
    )


def _context(surface: str) -> RequestContext:
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id=f"request-{surface}",
        session_id=f"session-{surface}",
    )
    context.extensions["composite_routing_surface"] = surface
    return context


def _build_resolver_with_real_composite(
    *,
    unavailable_backends: set[str] | None = None,
) -> BackendModelResolver:
    unavailable = unavailable_backends or set()

    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)

    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.side_effect = lambda model: model

    planning_phase_manager = MagicMock()
    planning_phase_manager.apply_if_needed = AsyncMock()

    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}

    routing_service = MagicMock()

    def _resolve_backend_instance(
        backend_type: str,
        _model_name: str,
        excluded_backends: set[str],
    ) -> str | None:
        if backend_type in unavailable or backend_type in excluded_backends:
            return None
        return backend_type

    def _resolve_model_only_backend(
        model_name: str,
        excluded_backends: set[str],
    ) -> str:
        _ = excluded_backends
        if model_name.startswith("claude"):
            return "anthropic"
        if model_name.startswith("gemini"):
            return "gemini"
        return "openai"

    routing_service.resolve_backend_instance.side_effect = _resolve_backend_instance
    routing_service.resolve_model_only_backend.side_effect = _resolve_model_only_backend

    return BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=AppConfig(),
        routing_service=routing_service,
    )


def _attach_deterministic_weighted_composite(
    resolver: BackendModelResolver,
    random_for_weights: Callable[[], float],
) -> None:
    diagnostics = CompositeDiagnosticsPublisher()
    leaf_resolver = CompositeLeafTargetResolverAdapter(backend_model_resolver=resolver)
    coordinator = CompositeRoutingCoordinator(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=random_for_weights
        ),
        leaf_target_resolver=leaf_resolver,
        diagnostics_publisher=diagnostics,
    )
    resolver._composite_routing_service = CompositeRoutingService(
        parser=CompositeSelectorParser(),
        coordinator=coordinator,
        diagnostics_publisher=diagnostics,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("surface", "expected_surface"),
    [
        ("main", "main"),
        ("auxiliary", "auxiliary"),
        ("quality_verifier", "quality_verifier"),
    ],
)
async def test_composite_entrypoint_uses_surface_from_context(
    surface: str, expected_surface: str
) -> None:
    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)
    routing_service = MagicMock()
    routing_service.resolve_backend_instance.return_value = "openai"
    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.return_value = (
        "openai:gpt-4|anthropic:claude-3-5-sonnet"
    )
    planning_phase_manager = MagicMock()
    planning_phase_manager.apply_if_needed = AsyncMock()
    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    composite_routing_service = MagicMock()
    composite_routing_service.resolve_target = AsyncMock(
        return_value=BackendTarget(
            backend="anthropic",
            model="claude-3-5-sonnet",
            uri_params={"temperature": "0.1"},
        )
    )
    resolver = BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=AppConfig(),
        routing_service=routing_service,
        composite_routing_service=composite_routing_service,
    )

    result = await resolver.resolve_target(
        _request("openai:gpt-4|anthropic:claude-3-5-sonnet"),
        context=_context(surface),
    )

    assert result.backend == "anthropic"
    assert result.model == "claude-3-5-sonnet"
    assert result.uri_params == {"temperature": "0.1"}
    assert composite_routing_service.resolve_target.await_args is not None
    routing_input = composite_routing_service.resolve_target.await_args.kwargs[
        "routing_input"
    ]
    assert routing_input.selector == "openai:gpt-4|anthropic:claude-3-5-sonnet"
    assert routing_input.surface.value == expected_surface
    assert routing_input.require_explicit_backend is False


@pytest.mark.asyncio
async def test_non_composite_model_uses_shared_composite_entrypoint() -> None:
    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)
    routing_service = MagicMock()
    routing_service.resolve_model_only_backend.return_value = "openai"
    routing_service.resolve_backend_instance.return_value = "openai"
    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.return_value = "gpt-4o"
    planning_phase_manager = MagicMock()
    planning_phase_manager.apply_if_needed = AsyncMock()
    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    composite_routing_service = MagicMock()
    composite_routing_service.resolve_target = AsyncMock(
        return_value=BackendTarget(
            backend="openai",
            model="gpt-4o",
            uri_params={},
        )
    )
    resolver = BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=AppConfig(),
        routing_service=routing_service,
        composite_routing_service=composite_routing_service,
    )

    result = await resolver.resolve_target(_request("gpt-4o"), context=_context("main"))

    assert result.backend == "openai"
    assert result.model == "gpt-4o"
    assert composite_routing_service.resolve_target.await_args is not None
    routing_input = composite_routing_service.resolve_target.await_args.kwargs[
        "routing_input"
    ]
    assert routing_input.selector == "gpt-4o"
    assert routing_input.surface.value == "main"
    assert routing_input.require_explicit_backend is False


@pytest.mark.asyncio
async def test_replacement_surface_translates_selector_and_publishes_deprecation() -> (
    None
):
    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)
    routing_service = MagicMock()
    routing_service.resolve_model_only_backend.return_value = "openai"
    routing_service.resolve_backend_instance.return_value = "openai"
    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.return_value = "openai:gpt-4o-mini"
    planning_phase_manager = MagicMock()
    planning_phase_manager.apply_if_needed = AsyncMock()
    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    composite_routing_service = MagicMock()
    composite_routing_service.resolve_target = AsyncMock(
        return_value=BackendTarget(
            backend="openai",
            model="gpt-4o-mini",
            uri_params={},
        )
    )
    resolver = BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=AppConfig(),
        routing_service=routing_service,
        composite_routing_service=composite_routing_service,
    )
    context = _context("replacement_bridge")
    context.extensions["replacement_effective_session_id"] = "replacement-session-1"

    result = await resolver.resolve_target(
        _request("openai:gpt-4o-mini"),
        context=context,
    )

    assert result.backend == "openai"
    assert result.model == "gpt-4o-mini"
    assert composite_routing_service.resolve_target.await_args is not None
    routing_input = composite_routing_service.resolve_target.await_args.kwargs[
        "routing_input"
    ]
    assert (
        routing_input.selector
        == "[weight=1]openai:gpt-4o-mini^[weight=1]openai:gpt-4o-mini"
    )
    assert routing_input.require_explicit_backend is True
    deprecation = context.extensions.get("replacement_deprecation")
    assert isinstance(deprecation, dict)
    assert deprecation.get("removal_timeline") == "N+1"


@pytest.mark.asyncio
async def test_replacement_surface_rejects_unsafe_mapping_without_session_identity() -> (
    None
):
    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)
    routing_service = MagicMock()
    routing_service.resolve_model_only_backend.return_value = "openai"
    routing_service.resolve_backend_instance.return_value = "openai"
    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.return_value = "openai:gpt-4o-mini"
    planning_phase_manager = MagicMock()
    planning_phase_manager.apply_if_needed = AsyncMock()
    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    resolver = BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=AppConfig(),
        routing_service=routing_service,
    )
    context = _context("replacement_bridge")

    with pytest.raises(ValidationError) as exc_info:
        await resolver.resolve_target(
            _request("openai:gpt-4o-mini"),
            context=context,
        )

    assert "replacement" in str(exc_info.value).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["main", "auxiliary", "quality_verifier"])
async def test_invalid_composite_selector_publishes_surface_consistent_diagnostics(
    surface: str,
) -> None:
    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)
    routing_service = MagicMock()
    routing_service.resolve_model_only_backend.return_value = "openai"
    routing_service.resolve_backend_instance.return_value = "openai"
    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.return_value = (
        "openai:gpt-4|anthropic:claude-3-5-sonnet^gemini:gemini-2.0-flash"
    )
    planning_phase_manager = MagicMock()
    planning_phase_manager.apply_if_needed = AsyncMock()
    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    resolver = BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=AppConfig(),
        routing_service=routing_service,
    )
    context = _context(surface)

    with pytest.raises(CompositeSelectorValidationError):
        await resolver.resolve_target(
            _request(
                "openai:gpt-4|anthropic:claude-3-5-sonnet^gemini:gemini-2.0-flash"
            ),
            context=context,
        )

    diagnostics = context.extensions.get("composite_routing_diagnostics")
    assert isinstance(diagnostics, dict)
    assert diagnostics.get("surface") == surface
    error_payload = diagnostics.get("error")
    assert isinstance(error_payload, dict)
    assert error_payload.get("code") == "routing_validation_failed"
    validation = error_payload.get("validation")
    assert isinstance(validation, dict)
    assert validation.get("code") == "unsupported_construct"


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["main", "auxiliary", "quality_verifier"])
async def test_parser_only_validation_errors_publish_diagnostics_without_top_level_operator(
    surface: str,
) -> None:
    resolver = _build_resolver_with_real_composite()
    context = _context(surface)

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        await resolver.resolve_target(
            _request("[weight=2]openai:gpt-4o-mini"),
            context=context,
        )

    assert exc_info.value.envelope.code.value == "unsupported_construct"
    diagnostics = context.extensions.get("composite_routing_diagnostics")
    assert isinstance(diagnostics, dict)
    assert diagnostics.get("surface") == surface
    error_payload = diagnostics.get("error")
    assert isinstance(error_payload, dict)
    assert error_payload.get("code") == "routing_validation_failed"
    validation = error_payload.get("validation")
    assert isinstance(validation, dict)
    assert validation.get("code") == "unsupported_construct"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selector", "expected_backend", "expected_model", "expected_uri_params"),
    [
        (
            "openai:gpt-4o?temperature=0.3",
            "openai",
            "gpt-4o",
            {"temperature": "0.3"},
        ),
        (
            "gpt-4o-mini?top_p=0.8",
            "openai",
            "gpt-4o-mini",
            {"top_p": "0.8"},
        ),
        (
            "openai.2:gpt-4o-mini?presence_penalty=1",
            "openai.2",
            "gpt-4o-mini",
            {"presence_penalty": "1"},
        ),
    ],
)
async def test_legacy_selector_semantics_stay_stable_for_composite_leaves(
    selector: str,
    expected_backend: str,
    expected_model: str,
    expected_uri_params: dict[str, str],
) -> None:
    resolver = _build_resolver_with_real_composite(
        unavailable_backends={"disabled-primary"}
    )

    standalone_target = await resolver.resolve_target(
        _request(selector),
        context=_context("main"),
    )
    composite_target = await resolver.resolve_target(
        _request(f"disabled-primary:gpt-4o|{selector}"),
        context=_context("main"),
    )

    assert standalone_target.backend == expected_backend
    assert standalone_target.model == expected_model
    assert standalone_target.uri_params == expected_uri_params

    assert composite_target.backend == standalone_target.backend
    assert composite_target.model == standalone_target.model
    assert composite_target.uri_params == standalone_target.uri_params


@pytest.mark.asyncio
async def test_composite_failover_to_explicit_leaf_ignores_conflicting_extra_backend_type() -> (
    None
):
    """Secondary explicit leaf must not inherit stale extra_body backend_type or URI params."""
    resolver = _build_resolver_with_real_composite(
        unavailable_backends={"disabled-primary"}
    )
    request = ChatRequest(
        model="disabled-primary:gpt-4o|anthropic:claude-3-5-sonnet",
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={
            "backend_type": "openai",
            "_resolved_uri_params": {"legacy": "param"},
        },
    )

    composite_target = await resolver.resolve_target(
        request,
        context=_context("main"),
    )

    assert composite_target.backend == "anthropic"
    assert composite_target.model == "claude-3-5-sonnet"
    assert composite_target.uri_params == {}


@pytest.mark.asyncio
async def test_replacement_surface_keeps_strict_selector_constraints() -> None:
    resolver = _build_resolver_with_real_composite()
    context = _context("replacement_bridge")
    context.extensions["replacement_effective_session_id"] = "replacement-session-1"

    with pytest.raises(ValidationError) as model_only_error:
        await resolver.resolve_target(
            _request("gpt-4o-mini"),
            context=context,
        )
    assert "explicit backend:model selector" in str(model_only_error.value).lower()

    with pytest.raises(ValidationError) as composite_error:
        await resolver.resolve_target(
            _request("openai:gpt-4o|anthropic:claude-3-5-sonnet"),
            context=context,
        )

    details = composite_error.value.details
    assert isinstance(details, dict)
    assert details.get("reason") == "unsupported_replacement_mapping"


@pytest.mark.asyncio
async def test_composite_failover_across_numbered_backend_instances() -> None:
    resolver = _build_resolver_with_real_composite(unavailable_backends={"openai.1"})
    selector = "openai.1:gpt-4o-mini?temperature=0.1|openai.2:gpt-4o?top_p=0.9"
    result = await resolver.resolve_target(
        _request(selector),
        context=_context("main"),
    )
    assert result.backend == "openai.2"
    assert result.model == "gpt-4o"
    assert result.uri_params == {"top_p": "0.9"}


@pytest.mark.asyncio
async def test_stale_leaf_resolution_flag_does_not_bypass_composite_failover() -> None:
    resolver = _build_resolver_with_real_composite(
        unavailable_backends={"openai-codex"}
    )
    request = ChatRequest(
        model=(
            "openai-codex:gpt-5.3-codex?reasoning_effort=low|"
            "anthropic:claude-3-5-sonnet?reasoning_effort=medium"
        ),
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={"_composite_leaf_resolution": True},
    )

    result = await resolver.resolve_target(
        request,
        context=_context("main"),
    )

    assert result.backend == "anthropic"
    assert result.model == "claude-3-5-sonnet"
    assert result.uri_params == {"reasoning_effort": "medium"}


@pytest.mark.asyncio
async def test_mixed_weighted_and_failover_selector_is_rejected_before_leaf_resolution() -> (
    None
):
    resolver = _build_resolver_with_real_composite()
    request = ChatRequest(
        model=(
            "[weight=1]openai-codex:gpt-5.3-codex?reasoning_effort=high^"
            "[weight=4]openai-codex:gpt-5.3-codex?reasoning_effort=low|"
            "[weight=2]openai-codex:gpt-5.3-codex?reasoning_effort=medium"
        ),
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={"_composite_leaf_resolution": True},
    )

    with pytest.raises(CompositeSelectorValidationError) as exc_info:
        await resolver.resolve_target(
            request,
            context=_context("main"),
        )

    assert exc_info.value.envelope.code.value == "unsupported_construct"


@pytest.mark.asyncio
async def test_internal_leaf_resolution_marker_bypasses_composite_reentry_without_context() -> (
    None
):
    resolver = _build_resolver_with_real_composite()
    leaf_selector = (
        "openai-codex:gpt-5.3-codex?"
        "reasoning_effort=low|[weight=2]openai-codex:gpt-5.3-codex"
        "?reasoning_effort=medium"
    )
    request = ChatRequest(
        model=leaf_selector,
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={
            COMPOSITE_LEAF_RESOLUTION_EXTRA_BODY_KEY: True,
            COMPOSITE_LEAF_SELECTOR_EXTRA_BODY_KEY: leaf_selector,
        },
    )

    result = await resolver.resolve_target(request, context=None)

    assert result.backend == "openai-codex"
    assert result.model == "gpt-5.3-codex"
    assert result.uri_params == {
        "reasoning_effort": (
            "low|[weight=2]openai-codex:gpt-5.3-codex?reasoning_effort=medium"
        )
    }


@pytest.mark.asyncio
async def test_composite_weighted_numbered_instances_respects_deterministic_random() -> (
    None
):
    resolver = _build_resolver_with_real_composite()
    _attach_deterministic_weighted_composite(resolver, random_for_weights=lambda: 0.6)
    selector = (
        "[weight=3]openai.1:gpt-branch-a?a=1^"
        "[weight=2]openai.2:gpt-branch-b?b=2^"
        "openai.2:gpt-branch-c?c=3"
    )
    result = await resolver.resolve_target(
        _request(selector),
        context=_context("main"),
    )
    assert result.backend == "openai.2"
    assert result.model == "gpt-branch-b"
    assert result.uri_params == {"b": "2"}


@pytest.mark.asyncio
async def test_model_alias_resolving_to_composite_selector_is_parsed_and_routed() -> (
    None
):
    """Verify that model aliases can resolve to composite selectors.

    When a model alias maps to a failover or weighted composite string,
    the resolved string should be parsed and routed through the composite
    routing system just like a directly-provided composite selector.
    """
    alias_pattern = "alias:minimax-m2"
    composite_replacement = "ollama:minimax-m2.7-cloud|opencode-zen:minimax-m2.5-free"

    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)

    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.side_effect = lambda model: (
        composite_replacement if model == alias_pattern else model
    )

    planning_phase_manager = MagicMock()
    planning_phase_manager.apply_if_needed = AsyncMock()

    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}

    routing_service = MagicMock()
    routing_service.resolve_backend_instance.side_effect = (
        lambda backend, model, excluded: backend
    )
    routing_service.resolve_model_only_backend.side_effect = lambda model, excluded: (
        "ollama" if "ollama" in model else "opencode-zen"
    )

    resolver = BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=AppConfig(),
        routing_service=routing_service,
    )

    result = await resolver.resolve_target(
        _request(alias_pattern),
        context=_context("main"),
    )

    calls = model_alias_resolver.resolve.call_args_list
    assert calls[0].args[0] == alias_pattern
    assert result.backend == "ollama"
    assert result.model == "minimax-m2.7-cloud"


@pytest.mark.asyncio
async def test_model_alias_composite_failover_advances_when_first_backend_unavailable() -> (
    None
):
    """Verify alias-resolved composite failover advances on first-branch failure."""
    alias_pattern = "alias:minimax-m2"
    composite_replacement = "ollama:minimax-m2.7-cloud|opencode-zen:minimax-m2.5-free"

    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)

    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.side_effect = lambda model: (
        composite_replacement if model == alias_pattern else model
    )

    planning_phase_manager = MagicMock()
    planning_phase_manager.apply_if_needed = AsyncMock()

    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}

    routing_service = MagicMock()

    def _resolve_backend_instance(
        backend_type: str,
        _model_name: str,
        excluded_backends: set[str],
    ) -> str | None:
        if backend_type == "ollama":
            return None
        return backend_type

    routing_service.resolve_backend_instance.side_effect = _resolve_backend_instance
    routing_service.resolve_model_only_backend.return_value = "opencode-zen"

    resolver = BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=AppConfig(),
        routing_service=routing_service,
    )

    result = await resolver.resolve_target(
        _request(alias_pattern),
        context=_context("main"),
    )

    assert result.backend == "opencode-zen"
    assert result.model == "minimax-m2.5-free"


@pytest.mark.asyncio
async def test_first_request_in_session_uses_first_tagged_branch() -> None:
    resolver = _build_resolver_with_real_composite()
    _attach_deterministic_weighted_composite(resolver, random_for_weights=lambda: 0.99)
    session = Session(
        session_id="session-main",
        state=SessionState(weighted_first_request_consumed=False),
    )
    resolver._session_service.get_session = AsyncMock(return_value=session)
    resolver._session_service.update_session = AsyncMock()

    result = await resolver.resolve_target(
        _request("[first]openai:first-model^[weight=100]openai:weighted-model"),
        context=_context("main"),
    )

    assert result.backend == "openai"
    assert result.model == "first-model"


@pytest.mark.asyncio
async def test_second_request_in_session_uses_weighted_routing() -> None:
    resolver = _build_resolver_with_real_composite()
    _attach_deterministic_weighted_composite(resolver, random_for_weights=lambda: 0.99)
    session = Session(
        session_id="session-main",
        state=SessionState(weighted_first_request_consumed=True),
    )
    resolver._session_service.get_session = AsyncMock(return_value=session)
    resolver._session_service.update_session = AsyncMock()

    result = await resolver.resolve_target(
        _request("[first]openai:first-model^[weight=100]openai:weighted-model"),
        context=_context("main"),
    )

    assert result.backend == "openai"
    assert result.model == "weighted-model"


@pytest.mark.asyncio
async def test_first_request_flag_is_consumed_after_routing() -> None:
    resolver = _build_resolver_with_real_composite()
    _attach_deterministic_weighted_composite(resolver, random_for_weights=lambda: 0.99)
    session = Session(
        session_id="session-main",
        state=SessionState(weighted_first_request_consumed=False),
    )
    resolver._session_service.get_session = AsyncMock(return_value=session)
    resolver._session_service.update_session = AsyncMock()

    await resolver.resolve_target(
        _request("[first]openai:first-model^[weight=100]openai:weighted-model"),
        context=_context("main"),
    )

    assert getattr(session.state, "weighted_first_request_consumed", False) is True
    assert resolver._session_service.update_session.await_count == 1


@pytest.mark.asyncio
async def test_no_session_treated_as_first_request() -> None:
    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)
    session_service.update_session = AsyncMock()
    routing_service = MagicMock()
    routing_service.resolve_backend_instance.return_value = "openai"
    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.return_value = (
        "[first]openai:first-model^[weight=100]openai:weighted-model"
    )
    planning_phase_manager = MagicMock()
    planning_phase_manager.apply_if_needed = AsyncMock()
    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    composite_routing_service = MagicMock()
    composite_routing_service.resolve_target = AsyncMock(
        return_value=BackendTarget(backend="openai", model="first-model", uri_params={})
    )
    resolver = BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=AppConfig(),
        routing_service=routing_service,
        composite_routing_service=composite_routing_service,
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="request-main",
        session_id=None,
    )
    context.extensions["composite_routing_surface"] = "main"

    await resolver.resolve_target(
        _request("[first]openai:first-model^[weight=100]openai:weighted-model"),
        context=context,
    )

    assert composite_routing_service.resolve_target.await_args is not None
    routing_input = composite_routing_service.resolve_target.await_args.kwargs[
        "routing_input"
    ]
    assert routing_input.prefer_first_weighted_branch is True
    assert session_service.get_session.await_count == 0
    assert session_service.update_session.await_count == 0


@pytest.mark.asyncio
async def test_first_request_flag_persisted_even_on_routing_error() -> None:
    session = Session(
        session_id="session-main",
        state=SessionState(weighted_first_request_consumed=False),
    )
    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=session)
    session_service.update_session = AsyncMock()
    routing_service = MagicMock()
    routing_service.resolve_backend_instance.return_value = "openai"
    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.return_value = (
        "[first]openai:first-model^[weight=100]openai:weighted-model"
    )
    planning_phase_manager = MagicMock()
    planning_phase_manager.apply_if_needed = AsyncMock()
    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    composite_routing_service = MagicMock()
    composite_routing_service.resolve_target = AsyncMock(
        side_effect=RoutingError(message="composite failed", details={"code": "test"})
    )
    resolver = BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=AppConfig(),
        routing_service=routing_service,
        composite_routing_service=composite_routing_service,
    )

    with pytest.raises(RoutingError):
        await resolver.resolve_target(
            _request("[first]openai:first-model^[weight=100]openai:weighted-model"),
            context=_context("main"),
        )

    assert getattr(session.state, "weighted_first_request_consumed", False) is True
    assert session_service.update_session.await_count == 1


@pytest.mark.asyncio
async def test_single_composite_leaf_parse_model_with_params_invoked_once() -> None:
    from src.core.domain import model_utils as model_utils_module

    resolver = _build_resolver_with_real_composite()
    _attach_deterministic_weighted_composite(resolver, lambda: 0.0)

    model = "openai-codex:gpt-5.4-mini?reasoning_effort=high"
    req = ChatRequest(
        model=model,
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={},
    )

    parse_calls = {"n": 0}
    real_parse = model_utils_module.parse_model_with_params

    def _counting_parse(*args: object, **kwargs: object) -> object:
        parse_calls["n"] += 1
        return real_parse(*args, **kwargs)

    with (
        patch(
            "src.core.services.composite_selector_parser.parse_model_with_params",
            side_effect=_counting_parse,
        ),
        patch(
            "src.core.services.backend_model_resolver.parse_model_with_params",
            side_effect=_counting_parse,
        ),
    ):
        target = await resolver.resolve_target(req, context=_context("main"))

    assert parse_calls["n"] == 1
    assert target.backend == "openai-codex"
    assert target.model == "gpt-5.4-mini"
    assert target.uri_params == {"reasoning_effort": "high"}
