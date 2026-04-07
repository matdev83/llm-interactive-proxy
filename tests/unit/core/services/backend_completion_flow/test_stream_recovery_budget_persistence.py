from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic.types import JsonValue
from src.core.common.exceptions import BackendError, RoutingError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget
from src.core.interfaces.failure_strategy_interface import FailureHandlingConfig
from src.core.services.backend_completion_flow.failure_recovery_executor import (
    FailureRecoveryExecutor,
)
from src.core.services.backend_completion_flow.service import BackendCompletionFlow
from src.core.services.failure_handling_strategy import DefaultFailureHandlingStrategy
from src.core.services.streaming.stream_recovery_budget import (
    get_or_init_stream_recovery_budget,
    mark_stream_meaningful_output,
)


def _new_request_context() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id="test-session",
        request_id="req-stream-budget",
    )


def _new_chat_request() -> ChatRequest:
    return ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )


def _build_flow(
    *,
    failover_executor: Any,
    connector_side_effect: Any,
) -> tuple[BackendCompletionFlow, AsyncMock]:
    availability_checker = MagicMock()
    availability_checker.check_backend_availability = AsyncMock()

    request_preparer = MagicMock()

    async def _prepare_request(request: ChatRequest, _context: RequestContext | None):
        backend = "openai.1"
        if isinstance(request.extra_body, dict):
            requested_backend = request.extra_body.get("backend_type")
            if isinstance(requested_backend, str) and requested_backend.strip():
                backend = requested_backend.strip()
        return ResolvedTarget(backend=backend, model="gpt-4", uri_params={})

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
    connector_invoker.invoke = AsyncMock(side_effect=connector_side_effect)

    flow = BackendCompletionFlow(
        availability_checker=availability_checker,
        request_preparer=request_preparer,
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


def test_get_or_init_stream_recovery_budget_initializes_once() -> None:
    context = _new_request_context()

    first_budget = get_or_init_stream_recovery_budget(context)
    assert first_budget is not None
    assert "recovery_budget_start_time" in context.extensions
    assert "attempted_backends" in context.extensions
    assert "retry_attempt" in context.extensions
    assert "meaningful_output_emitted" in context.extensions
    assert context.extensions["meaningful_output_emitted"] is False
    assert context.extensions["retry_attempt"] == 0

    first_start_time = context.extensions["recovery_budget_start_time"]
    second_budget = get_or_init_stream_recovery_budget(context)
    assert second_budget is not None
    assert second_budget.budget_start_time == first_budget.budget_start_time
    assert context.extensions["recovery_budget_start_time"] == first_start_time


def test_attempted_backends_list_is_persisted_across_helper_calls() -> None:
    context = _new_request_context()

    first_budget = get_or_init_stream_recovery_budget(context)
    assert first_budget is not None
    first_budget.attempted_backends.append("openai.1")

    second_budget = get_or_init_stream_recovery_budget(context)
    assert second_budget is not None
    assert second_budget.attempted_backends == ["openai.1"]
    assert context.extensions["attempted_backends"] == ["openai.1"]


def test_mark_stream_meaningful_output_is_idempotent() -> None:
    context = _new_request_context()
    get_or_init_stream_recovery_budget(context)

    mark_stream_meaningful_output(context)
    mark_stream_meaningful_output(context)

    assert context.extensions["meaningful_output_emitted"] is True


def test_get_or_init_stream_recovery_budget_sanitizes_invalid_extension_values() -> (
    None
):
    context = _new_request_context()
    context.extensions.update(
        {
            "recovery_budget_start_time": "bad",
            "attempted_backends": ["openai.1", 2, None],  # type: ignore[list-item]
            "retry_attempt": "not-an-int",
            "meaningful_output_emitted": "truthy",
        }
    )

    budget = get_or_init_stream_recovery_budget(context)

    assert budget is not None
    assert isinstance(context.extensions["recovery_budget_start_time"], float)
    assert context.extensions["attempted_backends"] == ["openai.1"]
    assert context.extensions["retry_attempt"] == 0
    assert context.extensions["meaningful_output_emitted"] is False


@pytest.mark.asyncio
async def test_call_completion_reuses_budget_start_time_across_recursive_calls() -> (
    None
):
    failover_executor = MagicMock()
    failover_executor.check_complex_failover = AsyncMock(return_value=False)
    failover_executor.apply_failure_recovery = AsyncMock(
        return_value=ResponseEnvelope(content={"ok": True})
    )

    flow, _invoke_mock = _build_flow(
        failover_executor=failover_executor,
        connector_side_effect=[
            BackendError(message="first attempt failed", backend_name="openai.1"),
            BackendError(message="second attempt failed", backend_name="openai.1"),
        ],
    )

    context = _new_request_context()
    request = _new_chat_request()

    await flow.call_completion(request=request, context=context, allow_failover=True)
    await flow.call_completion(request=request, context=context, allow_failover=True)

    assert failover_executor.apply_failure_recovery.call_count == 2
    first_start = failover_executor.apply_failure_recovery.call_args_list[0].kwargs[
        "start_time"
    ]
    second_start = failover_executor.apply_failure_recovery.call_args_list[1].kwargs[
        "start_time"
    ]
    assert first_start == second_start
    assert context.extensions["recovery_budget_start_time"] == first_start


@pytest.mark.asyncio
async def test_call_completion_uses_persisted_attempted_backends_list() -> None:
    failover_executor = MagicMock()
    failover_executor.check_complex_failover = AsyncMock(return_value=False)
    failover_executor.apply_failure_recovery = AsyncMock(
        return_value=ResponseEnvelope(content={"ok": True})
    )

    flow, _invoke_mock = _build_flow(
        failover_executor=failover_executor,
        connector_side_effect=BackendError(
            message="attempt failed",
            backend_name="openai.1",
        ),
    )

    context = _new_request_context()
    persisted_attempted_backends = ["seed-backend"]
    context.extensions["attempted_backends"] = cast(
        JsonValue, persisted_attempted_backends
    )
    request = _new_chat_request()

    await flow.call_completion(request=request, context=context, allow_failover=True)

    attempted_arg = failover_executor.apply_failure_recovery.call_args.kwargs[
        "attempted_backends"
    ]
    assert attempted_arg is persisted_attempted_backends
    assert attempted_arg == ["seed-backend"]


@pytest.mark.asyncio
async def test_budget_exhaustion_surfaces_attempt_budget_exhausted_after_failover_chain() -> (
    None
):
    failure_strategy = DefaultFailureHandlingStrategy(
        config=FailureHandlingConfig(
            max_silent_wait=30.0,
            total_timeout_budget=90.0,
            keepalive_interval=8.0,
            max_failover_hops=2,
            min_retry_wait=0.1,
        )
    )
    routing_service = MagicMock()

    def _find_alternatives(_model: str, exclude: list[str]) -> list[str]:
        if "openai.2" not in exclude:
            return ["openai.2"]
        return []

    routing_service.find_alternative_instances.side_effect = _find_alternatives

    failover_executor = FailureRecoveryExecutor(
        failover_planner=MagicMock(),
        failure_handling_strategy=failure_strategy,
        routing_service=routing_service,
        config=MagicMock(),
        failover_routes={},
    )

    flow, invoke_mock = _build_flow(
        failover_executor=failover_executor,
        connector_side_effect=[
            BackendError(message="primary backend failed", backend_name="openai.1"),
            BackendError(message="failover backend failed", backend_name="openai.2"),
        ],
    )

    context = _new_request_context()
    request = _new_chat_request()

    with pytest.raises(RoutingError) as exc_info:
        await flow.call_completion(
            request=request, context=context, allow_failover=True
        )

    assert exc_info.value.details.get("reason") == "attempt_budget_exhausted"
    assert context.extensions["attempted_backends"] == ["openai.1", "openai.2"]
    assert context.extensions["retry_attempt"] == 1
    assert context.extensions["is_retry"] is True
    assert context.extensions["b2bua_attempt_reason"] == "failover"
    assert invoke_mock.call_count == 2
