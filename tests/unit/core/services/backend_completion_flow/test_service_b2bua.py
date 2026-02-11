from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import BackendError
from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.services.b2bua_bleg_allocator_service import BlegAllocation
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


def _build_flow(
    *,
    a_session_id: str,
    allocator: Any | None,
    connector_side_effect: Any | None = None,
) -> tuple[BackendCompletionFlow, dict[str, Any]]:
    deps: dict[str, Any] = {
        "availability_checker": MagicMock(),
        "request_preparer": MagicMock(),
        "session_resolver": MagicMock(),
        "backend_invoker": MagicMock(),
        "failover_executor": MagicMock(),
        "wire_capture_orchestrator": MagicMock(),
        "usage_accounting_orchestrator": MagicMock(),
        "exception_normalizer": MagicMock(),
        "stream_formatting_service": MagicMock(),
        "connector_invoker": MagicMock(),
    }

    deps["exception_normalizer"].normalize.side_effect = lambda exc, _backend: exc
    deps["request_preparer"].prepare_request = AsyncMock(
        return_value=MagicMock(backend="openai", model="gpt-4", uri_params={})
    )
    deps["request_preparer"].synchronize_request_with_target.side_effect = (
        lambda req, _target: req
    )
    deps["failover_executor"].check_complex_failover = AsyncMock(return_value=False)
    deps["availability_checker"].check_backend_availability = AsyncMock()
    deps["session_resolver"].resolve_session = AsyncMock(
        return_value=(MagicMock(), a_session_id)
    )
    deps["backend_invoker"].acquire_backend = AsyncMock(return_value=MagicMock())
    deps["request_preparer"].prepare_backend_request = AsyncMock(
        side_effect=lambda request, *_args, **_kwargs: request
    )
    deps["request_preparer"].prepare_backend_kwargs = MagicMock(
        side_effect=lambda **kwargs: (
            {"session_id": kwargs["session_id_for_backend"]}
            if kwargs.get("session_id_for_backend")
            else {}
        )
    )

    deps["wire_capture_orchestrator"].prepare_wire_capture_context = AsyncMock(
        return_value=None
    )
    deps["wire_capture_orchestrator"].capture_wire_outbound = AsyncMock()
    deps["wire_capture_orchestrator"].capture_inbound_response = AsyncMock()
    deps["wire_capture_orchestrator"].detect_key_name.return_value = "test-key"
    deps["wire_capture_orchestrator"].wrap_inbound_stream.side_effect = (
        lambda **kwargs: kwargs["stream"]
    )
    deps["wire_capture_orchestrator"].capture_stream_completion = AsyncMock()

    deps["usage_accounting_orchestrator"].calculate_and_record_usage = AsyncMock(
        return_value=(0, None, None)
    )
    deps["usage_accounting_orchestrator"].wrap_response_for_usage = AsyncMock(
        side_effect=lambda **kwargs: kwargs["result"]
    )
    deps["usage_accounting_orchestrator"].handle_non_streaming_response = AsyncMock(
        side_effect=lambda **kwargs: kwargs["result"]
    )
    deps["usage_accounting_orchestrator"].handle_streaming_response = AsyncMock(
        side_effect=lambda **kwargs: kwargs["result"]
    )
    deps["usage_accounting_orchestrator"].handle_backend_error = AsyncMock()
    deps["usage_accounting_orchestrator"].handle_auth_failure = AsyncMock()

    if connector_side_effect is None:
        deps["connector_invoker"].invoke = AsyncMock(
            return_value=ResponseEnvelope(content={"ok": True}, headers={})
        )
    else:
        deps["connector_invoker"].invoke = AsyncMock(side_effect=connector_side_effect)

    flow = BackendCompletionFlow(
        availability_checker=deps["availability_checker"],
        request_preparer=deps["request_preparer"],
        session_resolver=deps["session_resolver"],
        backend_invoker=deps["backend_invoker"],
        failover_executor=deps["failover_executor"],
        wire_capture_orchestrator=deps["wire_capture_orchestrator"],
        usage_accounting_orchestrator=deps["usage_accounting_orchestrator"],
        exception_normalizer=deps["exception_normalizer"],
        stream_formatting_service=deps["stream_formatting_service"],
        connector_invoker=deps["connector_invoker"],
        b2bua_bleg_allocator=allocator,
    )
    return flow, deps


def _build_context(a_session_id: str) -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=MagicMock(),
        request_id="req-1",
        session_id=a_session_id,
        b2bua_identity=B2buaIdentity(a_session_id=a_session_id),
    )


@pytest.mark.asyncio
async def test_call_completion_uses_a_leg_for_state_and_b_leg_for_outbound() -> None:
    a_session_id = "llm-b2bua-a-1234"
    allocation = BlegAllocation(b_session_id="llm-b2bua-b-1234-1", seq=1)
    allocator = MagicMock()
    allocator.allocate = AsyncMock(return_value=allocation)
    flow, deps = _build_flow(a_session_id=a_session_id, allocator=allocator)

    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hello")],
    )
    context = _build_context(a_session_id)

    result = await flow.call_completion(
        request=request,
        stream=False,
        allow_failover=False,
        context=context,
    )

    assert isinstance(result, ResponseEnvelope)
    allocator.allocate.assert_awaited_once_with(
        a_session_id=a_session_id,
        backend_type="openai",
        effective_model="gpt-4",
        reason="initial",
    )
    deps["backend_invoker"].acquire_backend.assert_awaited_once_with(
        "openai",
        a_session_id,
    )

    kwargs_call = deps["request_preparer"].prepare_backend_kwargs.call_args.kwargs
    assert kwargs_call["session_id_for_backend"] == allocation.b_session_id
    attempt_context = kwargs_call["context"]
    assert attempt_context is not context
    assert attempt_context.session_id == a_session_id
    assert attempt_context.b2bua_identity is not None
    assert attempt_context.b2bua_identity.b_session_id == allocation.b_session_id

    usage_call = deps[
        "usage_accounting_orchestrator"
    ].calculate_and_record_usage.call_args
    assert usage_call.kwargs["session_id_for_backend"] == a_session_id

    invoke_call = deps["connector_invoker"].invoke.call_args
    invoke_context = invoke_call.kwargs["context"]
    assert invoke_context.session_id == a_session_id
    assert invoke_context.b2bua_identity is not None
    assert invoke_context.b2bua_identity.b_session_id == allocation.b_session_id

    assert context.b2bua_identity is not None
    assert context.b2bua_identity.b_session_id is None


@pytest.mark.asyncio
async def test_failover_attempt_allocates_new_b_leg_each_time() -> None:
    a_session_id = "llm-b2bua-a-5678"
    allocator = MagicMock()
    allocator.allocate = AsyncMock(
        side_effect=[
            BlegAllocation(b_session_id="llm-b2bua-b-5678-1", seq=1),
            BlegAllocation(b_session_id="llm-b2bua-b-5678-2", seq=2),
        ]
    )

    flow, deps = _build_flow(
        a_session_id=a_session_id,
        allocator=allocator,
        connector_side_effect=[
            BackendError(message="first attempt failed", backend_name="openai"),
            ResponseEnvelope(content={"ok": True}, headers={}),
        ],
    )

    async def _apply_failure_recovery(**kwargs: Any) -> ResponseEnvelope:
        callback = kwargs["call_completion_callback"]
        return await callback(
            request=kwargs["request"],
            stream=kwargs["is_streaming"],
            allow_failover=False,
            context=kwargs["context"],
        )

    deps["failover_executor"].apply_failure_recovery = AsyncMock(
        side_effect=_apply_failure_recovery
    )

    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="retry me")],
    )
    context = _build_context(a_session_id)

    result = await flow.call_completion(
        request=request,
        stream=False,
        allow_failover=True,
        context=context,
    )

    assert isinstance(result, ResponseEnvelope)
    assert allocator.allocate.await_count == 2

    prepared_calls = deps["request_preparer"].prepare_backend_kwargs.call_args_list
    outbound_session_ids = [
        call.kwargs["session_id_for_backend"] for call in prepared_calls
    ]
    assert outbound_session_ids == [
        "llm-b2bua-b-5678-1",
        "llm-b2bua-b-5678-2",
    ]

    acquire_calls = deps["backend_invoker"].acquire_backend.call_args_list
    assert [call.args[1] for call in acquire_calls] == [a_session_id, a_session_id]


@pytest.mark.asyncio
async def test_call_completion_logs_backend_attempt_with_a_and_b_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    a_session_id = "llm-b2bua-a-4242"
    allocation = BlegAllocation(b_session_id="llm-b2bua-b-4242-1", seq=1)
    allocator = MagicMock()
    allocator.allocate = AsyncMock(return_value=allocation)
    flow, _deps = _build_flow(a_session_id=a_session_id, allocator=allocator)

    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="log attempt")],
    )
    context = _build_context(a_session_id)

    with caplog.at_level(
        logging.INFO,
        logger="src.core.services.backend_completion_flow.service",
    ):
        await flow.call_completion(
            request=request,
            stream=False,
            allow_failover=False,
            context=context,
        )

    records = [
        record
        for record in caplog.records
        if record.message == "Dispatching backend attempt"
    ]
    assert records
    record = records[-1]
    assert getattr(record, "a_session_id", None) == a_session_id
    assert getattr(record, "b_session_id", None) == allocation.b_session_id
    assert getattr(record, "b_seq", None) == allocation.seq
