from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic.types import JsonValue
from src.core.common.exceptions import BackendError, RoutingError
from src.core.config.app_config import AppConfig
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.backend_completion_collaborators import IBackendRequestPreparer
from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget
from src.core.interfaces.domain_entities_interface import ISession
from src.core.services.backend_completion_flow.failure_recovery_executor import (
    FailureRecoveryExecutor,
)
from src.core.services.backend_completion_flow.service import BackendCompletionFlow
from src.core.services.backend_model_resolver import BackendModelResolver


def _new_request_context() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id="session-composite-runtime",
        request_id="req-composite-runtime",
    )


def _build_flow(
    *,
    failover_executor: FailureRecoveryExecutor,
    connector_side_effect: Any,
) -> tuple[BackendCompletionFlow, AsyncMock]:
    availability_checker = MagicMock()
    availability_checker.check_backend_availability = AsyncMock()

    request_preparer = MagicMock()

    async def _prepare_request(request: ChatRequest, _context: RequestContext | None):
        backend = "openai"
        model = request.model
        if ":" in request.model:
            backend, model = request.model.split(":", 1)
        return ResolvedTarget(backend=backend, model=model, uri_params={})

    request_preparer.prepare_request = AsyncMock(side_effect=_prepare_request)
    request_preparer.synchronize_request_with_target = MagicMock(
        side_effect=lambda req, _target: req
    )
    request_preparer.prepare_backend_request = AsyncMock(
        side_effect=lambda req, *_args, **_kwargs: req
    )
    request_preparer.prepare_backend_kwargs = MagicMock(return_value={})

    session_resolver = MagicMock()
    session_resolver.resolve_session = AsyncMock(return_value=(None, None))

    backend_invoker = MagicMock()
    backend_invoker.acquire_backend = AsyncMock(return_value=MagicMock())

    wire_capture_orchestrator = MagicMock()
    wire_capture_orchestrator.prepare_wire_capture_context = AsyncMock(
        return_value=None
    )
    wire_capture_orchestrator.capture_wire_outbound = AsyncMock()
    wire_capture_orchestrator.detect_key_name = MagicMock(return_value=None)
    wire_capture_orchestrator.capture_inbound_response = AsyncMock()
    wire_capture_orchestrator.wrap_inbound_stream.side_effect = lambda **kwargs: kwargs[
        "stream"
    ]

    usage_accounting = MagicMock()
    usage_accounting.calculate_and_record_usage = AsyncMock(
        return_value=(0, None, None)
    )
    usage_accounting.wrap_response_for_usage = AsyncMock(
        side_effect=lambda result, **_kwargs: result
    )
    usage_accounting.handle_streaming_response = AsyncMock(
        side_effect=lambda result, **_kwargs: result
    )
    usage_accounting.handle_non_streaming_response = AsyncMock(
        side_effect=lambda result, **_kwargs: result
    )
    usage_accounting.handle_auth_failure = AsyncMock()
    usage_accounting.handle_backend_error = AsyncMock()

    exception_normalizer = MagicMock()
    exception_normalizer.normalize = MagicMock(side_effect=lambda exc, *_args: exc)

    stream_formatting_service = MagicMock()
    stream_formatting_service.stream_as_sse_bytes = MagicMock(
        side_effect=lambda stream: stream
    )

    connector_invoker = MagicMock()
    if callable(connector_side_effect) or isinstance(
        connector_side_effect,
        list | tuple | Exception,
    ):
        connector_invoker.invoke = AsyncMock(side_effect=connector_side_effect)
    else:
        connector_invoker.invoke = AsyncMock(return_value=connector_side_effect)

    flow = BackendCompletionFlow(
        availability_checker=availability_checker,
        request_preparer=cast(IBackendRequestPreparer, request_preparer),
        session_resolver=session_resolver,
        backend_invoker=backend_invoker,
        failover_executor=failover_executor,
        wire_capture_orchestrator=wire_capture_orchestrator,
        usage_accounting_orchestrator=usage_accounting,
        exception_normalizer=exception_normalizer,
        stream_formatting_service=stream_formatting_service,
        connector_invoker=connector_invoker,
    )

    return flow, connector_invoker.invoke


class _ResolverBackedRequestPreparer:
    def __init__(self, resolver: BackendModelResolver) -> None:
        self._resolver = resolver

    async def prepare_request(
        self,
        request: CanonicalChatRequest,
        context: RequestContext | None,
    ) -> BackendTarget:
        return await self._resolver.resolve_target(request=request, context=context)

    def synchronize_request_with_target(
        self,
        request: CanonicalChatRequest,
        target: BackendTarget,
    ) -> CanonicalChatRequest:
        synchronized = self._resolver.synchronize_request_with_target(
            request=request,
            resolved=target,
        )
        return cast(CanonicalChatRequest, synchronized)

    async def prepare_backend_request(
        self,
        request: CanonicalChatRequest,
        backend_type: str,
        session: ISession | None,
        uri_params: dict[str, JsonValue],
    ) -> CanonicalChatRequest:
        _ = backend_type
        _ = session
        _ = uri_params
        return request

    def prepare_backend_kwargs(
        self,
        session_id_for_backend: str | None,
        session: ISession | None,
        context: RequestContext | None,
        backend_type: str,
    ) -> dict[str, JsonValue]:
        _ = session_id_for_backend
        _ = session
        _ = context
        _ = backend_type
        return {}


def _build_model_resolver(
    *,
    unavailable_backends: set[str] | None = None,
    max_hops: int = 2,
) -> BackendModelResolver:
    unavailable = unavailable_backends or set()

    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)

    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.side_effect = lambda selector: selector

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

    config = AppConfig(
        failure_handling={
            "max_failover_hops": max_hops,
        }
    )

    return BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=config,
        routing_service=routing_service,
    )


def _build_flow_with_resolver(
    *,
    resolver: BackendModelResolver,
    failover_executor: FailureRecoveryExecutor,
    connector_side_effect: Any,
) -> tuple[BackendCompletionFlow, AsyncMock]:
    availability_checker = MagicMock()
    availability_checker.check_backend_availability = AsyncMock()

    request_preparer = _ResolverBackedRequestPreparer(resolver)

    session_resolver = MagicMock()
    session_resolver.resolve_session = AsyncMock(return_value=(None, None))

    backend_invoker = MagicMock()
    backend_invoker.acquire_backend = AsyncMock(return_value=MagicMock())

    wire_capture_orchestrator = MagicMock()
    wire_capture_orchestrator.prepare_wire_capture_context = AsyncMock(
        return_value=None
    )
    wire_capture_orchestrator.capture_wire_outbound = AsyncMock()
    wire_capture_orchestrator.detect_key_name = MagicMock(return_value=None)
    wire_capture_orchestrator.capture_inbound_response = AsyncMock()
    wire_capture_orchestrator.wrap_inbound_stream.side_effect = lambda **kwargs: kwargs[
        "stream"
    ]

    usage_accounting = MagicMock()
    usage_accounting.calculate_and_record_usage = AsyncMock(
        return_value=(0, None, None)
    )
    usage_accounting.wrap_response_for_usage = AsyncMock(
        side_effect=lambda result, **_kwargs: result
    )
    usage_accounting.handle_streaming_response = AsyncMock(
        side_effect=lambda result, **_kwargs: result
    )
    usage_accounting.handle_non_streaming_response = AsyncMock(
        side_effect=lambda result, **_kwargs: result
    )
    usage_accounting.handle_auth_failure = AsyncMock()
    usage_accounting.handle_backend_error = AsyncMock()

    exception_normalizer = MagicMock()
    exception_normalizer.normalize = MagicMock(side_effect=lambda exc, *_args: exc)

    stream_formatting_service = MagicMock()
    stream_formatting_service.stream_as_sse_bytes = MagicMock(
        side_effect=lambda stream: stream
    )

    connector_invoker = MagicMock()
    if callable(connector_side_effect) or isinstance(
        connector_side_effect,
        list | tuple | Exception,
    ):
        connector_invoker.invoke = AsyncMock(side_effect=connector_side_effect)
    else:
        connector_invoker.invoke = AsyncMock(return_value=connector_side_effect)

    flow = BackendCompletionFlow(
        availability_checker=availability_checker,
        request_preparer=cast(IBackendRequestPreparer, request_preparer),
        session_resolver=session_resolver,
        backend_invoker=backend_invoker,
        failover_executor=failover_executor,
        wire_capture_orchestrator=wire_capture_orchestrator,
        usage_accounting_orchestrator=usage_accounting,
        exception_normalizer=exception_normalizer,
        stream_formatting_service=stream_formatting_service,
        connector_invoker=connector_invoker,
    )
    return flow, connector_invoker.invoke


def _new_chat_request() -> ChatRequest:
    return ChatRequest(
        model="openai:gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        extra_body={"backend_type": "openai"},
    )


def _context_for_surface(surface: str) -> RequestContext:
    context = _new_request_context()
    if surface == "auxiliary":
        context.extensions["call_purpose"] = "auxiliary"
    elif surface == "quality_verifier":
        context.extensions["call_purpose"] = "quality_verifier"
    return context


@pytest.mark.asyncio
async def test_runtime_bridge_advances_composite_failover_before_output() -> None:
    failover_executor = FailureRecoveryExecutor(
        failover_planner=MagicMock(),
        failure_handling_strategy=None,
        routing_service=MagicMock(),
        config=MagicMock(),
        failover_routes={},
    )

    flow, invoke_mock = _build_flow(
        failover_executor=failover_executor,
        connector_side_effect=[
            BackendError("primary failed", "openai"),
            ResponseEnvelope(content={"ok": True}),
        ],
    )

    context = _new_request_context()
    context.extensions["composite_routing_state"] = {
        "mode": "failover",
        "branches": ["openai:gpt-4", "anthropic:claude-3-5-sonnet"],
        "next_index": 1,
        "hop_count": 0,
        "max_hops": 2,
    }

    response = await flow.call_completion(
        request=_new_chat_request(),
        context=context,
        allow_failover=True,
    )

    assert response.content == {"ok": True}
    assert invoke_mock.call_count == 2
    second_call_request = invoke_mock.call_args_list[1].kwargs["canonical_request"]
    assert second_call_request.model == "anthropic:claude-3-5-sonnet"
    assert context.extensions["retry_attempt"] == 1
    assert context.extensions["last_retry_reason"] == "composite_failover"
    state = cast(dict[str, Any], context.extensions["composite_routing_state"])
    assert state["next_index"] == 2
    assert state["hop_count"] == 1


@pytest.mark.asyncio
async def test_runtime_bridge_blocks_composite_failover_after_meaningful_output() -> (
    None
):
    failover_executor = FailureRecoveryExecutor(
        failover_planner=MagicMock(),
        failure_handling_strategy=None,
        routing_service=MagicMock(),
        config=MagicMock(),
        failover_routes={},
    )

    flow, invoke_mock = _build_flow(
        failover_executor=failover_executor,
        connector_side_effect=BackendError("primary failed", "openai"),
    )

    context = _new_request_context()
    context.extensions["meaningful_output_emitted"] = True
    context.extensions["composite_routing_state"] = {
        "mode": "failover",
        "branches": ["openai:gpt-4", "anthropic:claude-3-5-sonnet"],
        "next_index": 1,
        "hop_count": 0,
        "max_hops": 2,
    }

    with pytest.raises(BackendError):
        await flow.call_completion(
            request=_new_chat_request(),
            context=context,
            allow_failover=True,
        )

    assert invoke_mock.call_count == 1
    state = cast(dict[str, Any], context.extensions["composite_routing_state"])
    assert state["next_index"] == 1
    assert state["hop_count"] == 0


@pytest.mark.asyncio
async def test_runtime_bridge_surfaces_exhaustion_when_shared_budget_is_spent() -> None:
    failover_executor = FailureRecoveryExecutor(
        failover_planner=MagicMock(),
        failure_handling_strategy=None,
        routing_service=MagicMock(),
        config=MagicMock(),
        failover_routes={},
    )

    flow, invoke_mock = _build_flow(
        failover_executor=failover_executor,
        connector_side_effect=BackendError("primary failed", "openai"),
    )

    context = _new_request_context()
    context.extensions["composite_routing_state"] = {
        "mode": "failover",
        "branches": ["openai:gpt-4", "anthropic:claude-3-5-sonnet"],
        "next_index": 1,
        "hop_count": 1,
        "max_hops": 1,
    }

    with pytest.raises(RoutingError) as exc_info:
        await flow.call_completion(
            request=_new_chat_request(),
            context=context,
            allow_failover=True,
        )

    assert invoke_mock.call_count == 1
    assert exc_info.value.details["reason"] == "attempt_budget_exhausted"
    diagnostics = context.extensions.get("composite_routing_diagnostics")
    assert isinstance(diagnostics, dict)
    exhaustion = diagnostics.get("exhaustion")
    assert isinstance(exhaustion, dict)
    assert exhaustion.get("reason") == "attempt_budget_exhausted"


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["main", "auxiliary", "quality_verifier"])
async def test_route_strings_failover_left_to_right_across_surfaces(
    surface: str,
) -> None:
    failover_executor = FailureRecoveryExecutor(
        failover_planner=MagicMock(),
        failure_handling_strategy=None,
        routing_service=MagicMock(),
        config=MagicMock(),
        failover_routes={},
    )
    resolver = _build_model_resolver(unavailable_backends={"openai"})
    flow, invoke_mock = _build_flow_with_resolver(
        resolver=resolver,
        failover_executor=failover_executor,
        connector_side_effect=ResponseEnvelope(content={"ok": True}),
    )

    response = await flow.call_completion(
        request=ChatRequest(
            model="openai:gpt-4|anthropic:claude-3-5-sonnet",
            messages=[ChatMessage(role="user", content="Hello")],
            extra_body={},
        ),
        context=_context_for_surface(surface),
        allow_failover=True,
    )

    assert response.content == {"ok": True}
    assert invoke_mock.call_count == 1
    dispatched_request = invoke_mock.call_args.kwargs["canonical_request"]
    assert dispatched_request.extra_body is not None
    assert dispatched_request.extra_body.get("backend_type") == "anthropic"
    assert dispatched_request.model == "claude-3-5-sonnet"


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["main", "auxiliary", "quality_verifier"])
async def test_route_strings_failover_exhaustion_is_deterministic_across_surfaces(
    surface: str,
) -> None:
    failover_executor = FailureRecoveryExecutor(
        failover_planner=MagicMock(),
        failure_handling_strategy=None,
        routing_service=MagicMock(),
        config=MagicMock(),
        failover_routes={},
    )
    resolver = _build_model_resolver(unavailable_backends={"openai", "anthropic"})
    flow, invoke_mock = _build_flow_with_resolver(
        resolver=resolver,
        failover_executor=failover_executor,
        connector_side_effect=ResponseEnvelope(content={"ok": True}),
    )
    context = _context_for_surface(surface)

    with pytest.raises(RoutingError) as exc_info:
        await flow.call_completion(
            request=ChatRequest(
                model="openai:gpt-4|anthropic:claude-3-5-sonnet",
                messages=[ChatMessage(role="user", content="Hello")],
                extra_body={},
            ),
            context=context,
            allow_failover=True,
        )

    assert exc_info.value.details["reason"] == "failover_exhausted"
    assert invoke_mock.call_count == 0
    diagnostics = context.extensions.get("composite_routing_diagnostics")
    assert isinstance(diagnostics, dict)
    exhaustion = diagnostics.get("exhaustion")
    assert isinstance(exhaustion, dict)
    assert exhaustion.get("reason") == "failover_exhausted"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("surface", "random_value", "expected_backend", "expected_model"),
    [
        ("main", 0.0, "openai", "gpt-4"),
        ("auxiliary", 0.99, "anthropic", "claude-3-5-sonnet"),
        ("quality_verifier", 0.0, "openai", "gpt-4"),
    ],
)
async def test_weighted_route_strings_choose_exactly_one_branch_per_surface(
    surface: str,
    random_value: float,
    expected_backend: str,
    expected_model: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.core.services.weighted_branch_selector.random.random",
        lambda: random_value,
    )

    failover_executor = FailureRecoveryExecutor(
        failover_planner=MagicMock(),
        failure_handling_strategy=None,
        routing_service=MagicMock(),
        config=MagicMock(),
        failover_routes={},
    )
    resolver = _build_model_resolver()
    flow, invoke_mock = _build_flow_with_resolver(
        resolver=resolver,
        failover_executor=failover_executor,
        connector_side_effect=ResponseEnvelope(content={"ok": True}),
    )

    response = await flow.call_completion(
        request=ChatRequest(
            model="[weight=1]openai:gpt-4^[weight=1]anthropic:claude-3-5-sonnet",
            messages=[ChatMessage(role="user", content="Hello")],
            extra_body={},
        ),
        context=_context_for_surface(surface),
        allow_failover=True,
    )

    assert response.content == {"ok": True}
    assert invoke_mock.call_count == 1
    dispatched_request = invoke_mock.call_args.kwargs["canonical_request"]
    assert dispatched_request.extra_body is not None
    assert dispatched_request.extra_body.get("backend_type") == expected_backend
    assert dispatched_request.model == expected_model


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["main", "auxiliary", "quality_verifier"])
async def test_shared_hop_bound_applies_across_retries_and_failover_for_route_strings(
    surface: str,
) -> None:
    failover_executor = FailureRecoveryExecutor(
        failover_planner=MagicMock(),
        failure_handling_strategy=None,
        routing_service=MagicMock(),
        config=MagicMock(),
        failover_routes={},
    )
    resolver = _build_model_resolver(max_hops=1)
    flow, invoke_mock = _build_flow_with_resolver(
        resolver=resolver,
        failover_executor=failover_executor,
        connector_side_effect=[
            BackendError("primary failed", "openai"),
            BackendError("secondary failed", "anthropic"),
        ],
    )
    context = _context_for_surface(surface)

    with pytest.raises(RoutingError) as exc_info:
        await flow.call_completion(
            request=ChatRequest(
                model="openai:gpt-4?temperature=0.2|anthropic:claude-3-5-sonnet|gemini:gemini-2.0-flash",
                messages=[ChatMessage(role="user", content="Hello")],
                extra_body={},
            ),
            context=context,
            allow_failover=True,
        )

    assert exc_info.value.details["reason"] == "attempt_budget_exhausted"
    assert invoke_mock.call_count == 2

    first_request = invoke_mock.call_args_list[0].kwargs["canonical_request"]
    second_request = invoke_mock.call_args_list[1].kwargs["canonical_request"]
    assert first_request.extra_body is not None
    assert second_request.extra_body is not None
    assert first_request.extra_body.get("backend_type") == "openai"
    assert second_request.extra_body.get("backend_type") == "anthropic"
    second_uri_params = second_request.extra_body.get("_resolved_uri_params")
    assert second_uri_params in ({}, None)

    assert context.extensions["retry_attempt"] == 1
    state = cast(dict[str, Any], context.extensions["composite_routing_state"])
    assert state["hop_count"] == 1
    assert state["max_hops"] == 1

    diagnostics = context.extensions.get("composite_routing_diagnostics")
    assert isinstance(diagnostics, dict)
    exhaustion = diagnostics.get("exhaustion")
    assert isinstance(exhaustion, dict)
    assert exhaustion.get("reason") == "attempt_budget_exhausted"
