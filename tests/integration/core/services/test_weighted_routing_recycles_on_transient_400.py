from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope


def _new_request_context() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id="session-weighted-recycle",
        request_id="req-weighted-recycle",
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
        backend = "zai-coding-plan"
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
        request_preparer=request_preparer,  # type: ignore[arg-type]
        session_resolver=session_resolver,
        backend_invoker=backend_invoker,
        failover_executor=failover_executor,
        wire_capture_orchestrator=wire_capture_orchestrator,
        usage_accounting_orchestrator=usage_accounting,
        exception_normalizer=exception_normalizer,
        stream_formatting_service=stream_formatting_service,
        connector_invoker=connector_invoker,
    )

    return flow, connector_invoker.invoke  # type: ignore[return-value]


def _new_chat_request() -> ChatRequest:
    return ChatRequest(
        model="zai-coding-plan:glm-5.1",
        messages=[ChatMessage(role="user", content="Explain this code.")],
        extra_body={"backend_type": "zai-coding-plan"},
    )


def _build_model_resolver() -> BackendModelResolver:
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
        if backend_type in excluded_backends:
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
            "max_failover_hops": 4,
        },
    )

    return BackendModelResolver(
        session_service=session_service,
        model_alias_resolver=model_alias_resolver,
        planning_phase_manager=planning_phase_manager,
        backend_lifecycle_manager=backend_lifecycle_manager,
        config=config,
        routing_service=routing_service,
    )


class _ResolverBackedRequestPreparer:
    def __init__(self, resolver: BackendModelResolver) -> None:
        self._resolver = resolver

    async def prepare_request(
        self,
        request: ChatRequest,
        context: RequestContext | None,
    ) -> Any:
        return await self._resolver.resolve_target(request=request, context=context)

    def synchronize_request_with_target(
        self,
        request: ChatRequest,
        target: Any,
    ) -> ChatRequest:
        synchronized = self._resolver.synchronize_request_with_target(
            request=request,
            resolved=target,
        )
        return cast(ChatRequest, synchronized)

    async def prepare_backend_request(
        self,
        request: ChatRequest,
        backend_type: str,
        session: ISession | None,
        uri_params: dict[str, Any],
    ) -> ChatRequest:
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
    ) -> dict[str, Any]:
        _ = session_id_for_backend
        _ = session
        _ = context
        _ = backend_type
        return {}


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
        request_preparer=request_preparer,  # type: ignore[arg-type]
        session_resolver=session_resolver,
        backend_invoker=backend_invoker,
        failover_executor=failover_executor,
        wire_capture_orchestrator=wire_capture_orchestrator,
        usage_accounting_orchestrator=usage_accounting,
        exception_normalizer=exception_normalizer,
        stream_formatting_service=stream_formatting_service,
        connector_invoker=connector_invoker,
    )
    return flow, connector_invoker.invoke  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_weighted_routing_recycles_on_transient_400_without_surfacing() -> None:
    """End-to-end: weighted routing recycles candidates on transient 400.

    Scenario:
    - Branch 0 (zai-coding-plan:glm-5.1) returns a transient 400.
    - Branch 1 (qwen-oauth:coder-model) succeeds.
    - The system reroutes to the alternate branch within budget.
    """
    rng_values = [0.0, 0.99]
    idx = 0

    def _rng() -> float:
        nonlocal idx
        val = rng_values[idx % len(rng_values)]
        idx += 1
        return val

    composite_bridge = CompositeFailureRecoveryBridge(
        weighted_branch_selector=WeightedBranchSelector(random_value_provider=_rng),
    )
    failover_executor = FailureRecoveryExecutor(
        failover_planner=MagicMock(),
        failure_handling_strategy=None,
        routing_service=MagicMock(),
        config=MagicMock(),
        failover_routes={},
        composite_failure_recovery_bridge=composite_bridge,
    )

    flow, invoke_mock = _build_flow(
        failover_executor=failover_executor,
        connector_side_effect=[
            BackendError("Backend returned 400 error", status_code=400),
            ResponseEnvelope(content={"ok": True}),
        ],
    )

    context = _new_request_context()
    context.extensions["composite_routing_state"] = {
        "mode": "weighted_retry",
        "branches": [
            {"selector": "zai-coding-plan:glm-5.1", "weight": 1},
            {"selector": "qwen-oauth:coder-model", "weight": 1},
        ],
        "excluded_selectors": [],
        "selected_selector": "zai-coding-plan:glm-5.1",
        "hop_count": 0,
        "max_hops": 3,
    }

    response = await flow.call_completion(
        request=_new_chat_request(),
        context=context,
        allow_failover=True,
    )

    assert response.content == {"ok": True}
    assert invoke_mock.call_count == 2

    second_call_request = invoke_mock.call_args_list[1].kwargs["canonical_request"]
    assert second_call_request.model == "qwen-oauth:coder-model"

    state = context.extensions["composite_routing_state"]
    assert isinstance(state, dict)
    assert state["selected_selector"] == "qwen-oauth:coder-model"
    assert "zai-coding-plan:glm-5.1" in state["excluded_selectors"]
    assert state["hop_count"] == 1


@pytest.mark.asyncio
async def test_weighted_routing_recycles_all_candidates_within_hop_budget() -> None:
    """End-to-end: when all weighted branches fail once, recycling resumes.

    Scenario:
    - Branch 0 (zai-coding-plan) returns 400.
    - Branch 1 (qwen-oauth) returns 400.
    - Hop 2 recycles zai-coding-plan (which now succeeds).
    """
    rng_values = [0.0, 0.99, 0.5]
    idx = 0

    def _rng() -> float:
        nonlocal idx
        val = rng_values[idx % len(rng_values)]
        idx += 1
        return val

    composite_bridge = CompositeFailureRecoveryBridge(
        weighted_branch_selector=WeightedBranchSelector(random_value_provider=_rng),
    )
    failover_executor = FailureRecoveryExecutor(
        failover_planner=MagicMock(),
        failure_handling_strategy=None,
        routing_service=MagicMock(),
        config=MagicMock(),
        failover_routes={},
        composite_failure_recovery_bridge=composite_bridge,
    )

    flow, invoke_mock = _build_flow(
        failover_executor=failover_executor,
        connector_side_effect=[
            BackendError("zai 400", status_code=400),
            BackendError("qwen 400", status_code=400),
            ResponseEnvelope(content={"ok": True}),
        ],
    )

    context = _new_request_context()
    context.extensions["composite_routing_state"] = {
        "mode": "weighted_retry",
        "branches": [
            {"selector": "zai-coding-plan:glm-5.1", "weight": 1},
            {"selector": "qwen-oauth:coder-model", "weight": 1},
        ],
        "excluded_selectors": [],
        "selected_selector": "zai-coding-plan:glm-5.1",
        "hop_count": 0,
        "max_hops": 4,
    }

    response = await flow.call_completion(
        request=_new_chat_request(),
        context=context,
        allow_failover=True,
    )

    assert response.content == {"ok": True}
    assert invoke_mock.call_count == 3

    third_call_request = invoke_mock.call_args_list[2].kwargs["canonical_request"]
    assert third_call_request.model == "zai-coding-plan:glm-5.1"

    state = context.extensions["composite_routing_state"]
    assert isinstance(state, dict)
    assert state["selected_selector"] == "zai-coding-plan:glm-5.1"
    assert state["hop_count"] == 3


@pytest.mark.asyncio
async def test_weighted_routing_recycles_with_resolver_backend() -> None:
    """Same recycling scenario but with a real BackendModelResolver wiring.

    This exercises the full path including backend resolution and request
    synchronization that production uses.
    """
    rng_values = [0.0, 0.99, 0.5]
    idx = 0

    def _rng() -> float:
        nonlocal idx
        val = rng_values[idx % len(rng_values)]
        idx += 1
        return val

    resolver = _build_model_resolver()
    composite_bridge = CompositeFailureRecoveryBridge(
        weighted_branch_selector=WeightedBranchSelector(random_value_provider=_rng),
    )
    failover_executor = FailureRecoveryExecutor(
        failover_planner=MagicMock(),
        failure_handling_strategy=None,
        routing_service=MagicMock(),
        config=MagicMock(),
        failover_routes={},
        composite_failure_recovery_bridge=composite_bridge,
    )

    flow, invoke_mock = _build_flow_with_resolver(
        resolver=resolver,
        failover_executor=failover_executor,
        connector_side_effect=[
            BackendError("zai 400", status_code=400),
            BackendError("qwen 400", status_code=400),
            ResponseEnvelope(content={"ok": True}),
        ],
    )

    context = _new_request_context()
    context.extensions["composite_routing_state"] = {
        "mode": "weighted_retry",
        "branches": [
            {"selector": "zai-coding-plan:glm-5.1", "weight": 1},
            {"selector": "qwen-oauth:coder-model", "weight": 1},
        ],
        "excluded_selectors": [],
        "selected_selector": "zai-coding-plan:glm-5.1",
        "hop_count": 0,
        "max_hops": 4,
    }

    response = await flow.call_completion(
        request=ChatRequest(
            model="zai-coding-plan:glm-5.1",
            messages=[ChatMessage(role="user", content="Explain this code.")],
            extra_body={"backend_type": "zai-coding-plan"},
        ),
        context=context,
        allow_failover=True,
    )

    assert response.content == {"ok": True}
    assert invoke_mock.call_count == 3

    state = context.extensions["composite_routing_state"]
    assert isinstance(state, dict)
    assert state["selected_selector"] == "zai-coding-plan:glm-5.1"
    assert state["hop_count"] == 3
