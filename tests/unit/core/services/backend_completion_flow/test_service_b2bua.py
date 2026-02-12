from __future__ import annotations

import asyncio
import logging
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import BackendError
from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.services.auxiliary_identity import build_auxiliary_effective_session_id
from src.core.services.b2bua_bleg_allocator_service import BlegAllocation
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


def _build_flow(
    *,
    a_session_id: str,
    allocator: Any | None,
    connector_side_effect: Any | None = None,
    resilience_coordinator: Any | None = None,
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
        resilience_coordinator=resilience_coordinator,
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
async def test_failover_enabled_records_attempt_failure_in_resilience_state() -> None:
    a_session_id = "llm-b2bua-a-9090"
    resilience = MagicMock()
    resilience.record_failure = MagicMock()

    flow, deps = _build_flow(
        a_session_id=a_session_id,
        allocator=None,
        connector_side_effect=BackendError(
            message="temporary backend failure",
            backend_name="openai",
        ),
        resilience_coordinator=resilience,
    )

    deps["failover_executor"].apply_failure_recovery = AsyncMock(
        return_value=ResponseEnvelope(content={"ok": True}, headers={})
    )

    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="trigger failover path")],
    )
    context = _build_context(a_session_id)

    result = await flow.call_completion(
        request=request,
        stream=False,
        allow_failover=True,
        context=context,
    )

    assert isinstance(result, ResponseEnvelope)
    resilience.record_failure.assert_called_once()
    record_args = resilience.record_failure.call_args.args
    assert record_args[0] == "openai"
    assert record_args[1] == "gpt-4"
    assert isinstance(record_args[2], BackendError)


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
        retry_context = kwargs["context"]
        if isinstance(retry_context, RequestContext):
            retry_context.extensions["retry_attempt"] = 1
            retry_context.extensions["is_retry"] = True
        result = await callback(
            request=kwargs["request"],
            stream=kwargs["is_streaming"],
            allow_failover=False,
            context=retry_context,
        )
        return cast(ResponseEnvelope, result)

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


@pytest.mark.asyncio
async def test_auxiliary_request_skips_b_leg_allocation_and_uses_auxiliary_identity() -> (
    None
):
    a_session_id = "llm-b2bua-a-7001"
    auxiliary_purpose = "openai:gpt-4"
    operation_key = "req:req-1"
    expected_auxiliary_session_id = build_auxiliary_effective_session_id(
        root_session_id=a_session_id,
        purpose=auxiliary_purpose,
        operation_key=operation_key,
        attempt_ordinal=1,
    )
    allocator = MagicMock()
    allocator.allocate = AsyncMock(
        return_value=BlegAllocation(b_session_id="llm-b2bua-b-7001-1", seq=1)
    )
    flow, deps = _build_flow(a_session_id=a_session_id, allocator=allocator)
    deps["session_resolver"].resolve_session = AsyncMock(
        return_value=(MagicMock(), expected_auxiliary_session_id)
    )

    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="auxiliary call")],
    )
    context = _build_context(a_session_id)
    context.extensions.update(
        {
            "auxiliary_request": True,
            "auxiliary_root_session_id": a_session_id,
            "auxiliary_purpose": auxiliary_purpose,
            "auxiliary_operation_key": operation_key,
        }
    )

    result = await flow.call_completion(
        request=request,
        stream=False,
        allow_failover=False,
        context=context,
    )

    assert isinstance(result, ResponseEnvelope)
    allocator.allocate.assert_not_awaited()
    kwargs_call = deps["request_preparer"].prepare_backend_kwargs.call_args.kwargs
    assert kwargs_call["session_id_for_backend"] == expected_auxiliary_session_id


@pytest.mark.asyncio
async def test_auxiliary_request_uses_auxiliary_id_when_allocator_fails_open() -> None:
    a_session_id = "llm-b2bua-a-7002"
    auxiliary_purpose = "openai:gpt-4"
    operation_key = "req:req-1"
    expected_auxiliary_session_id = build_auxiliary_effective_session_id(
        root_session_id=a_session_id,
        purpose=auxiliary_purpose,
        operation_key=operation_key,
        attempt_ordinal=1,
    )
    allocator = MagicMock()
    allocator.allocate = AsyncMock(side_effect=RuntimeError("allocator unavailable"))
    flow, deps = _build_flow(a_session_id=a_session_id, allocator=allocator)
    deps["session_resolver"].resolve_session = AsyncMock(
        return_value=(MagicMock(), expected_auxiliary_session_id)
    )

    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="auxiliary call")],
    )
    context = _build_context(a_session_id)
    context.extensions.update(
        {
            "auxiliary_request": True,
            "auxiliary_root_session_id": a_session_id,
            "auxiliary_purpose": auxiliary_purpose,
            "auxiliary_operation_key": operation_key,
        }
    )

    result = await flow.call_completion(
        request=request,
        stream=False,
        allow_failover=False,
        context=context,
    )

    assert isinstance(result, ResponseEnvelope)
    kwargs_call = deps["request_preparer"].prepare_backend_kwargs.call_args.kwargs
    assert kwargs_call["session_id_for_backend"] == expected_auxiliary_session_id


@pytest.mark.asyncio
async def test_auxiliary_retry_uses_deterministic_attempt_ordinal_identity() -> None:
    a_session_id = "llm-b2bua-a-7010"
    auxiliary_purpose = "openai:gpt-4"
    operation_key = "req:req-1"
    allocator = MagicMock()
    allocator.allocate = AsyncMock(
        return_value=BlegAllocation(b_session_id="llm-b2bua-b-7010-1", seq=1)
    )

    flow, deps = _build_flow(
        a_session_id=a_session_id,
        allocator=allocator,
        connector_side_effect=[
            BackendError(message="first attempt failed", backend_name="openai"),
            ResponseEnvelope(content={"ok": True}, headers={}),
        ],
    )

    async def _resolve_session(
        context: RequestContext | None, _request: CanonicalChatRequest
    ) -> tuple[object, str]:
        assert context is not None
        effective_auxiliary_id = context.extensions.get(
            "auxiliary_effective_session_id"
        )
        assert isinstance(effective_auxiliary_id, str)
        return MagicMock(), effective_auxiliary_id

    deps["session_resolver"].resolve_session = AsyncMock(side_effect=_resolve_session)

    async def _apply_failure_recovery(**kwargs: Any) -> ResponseEnvelope:
        callback = kwargs["call_completion_callback"]
        retry_context = kwargs["context"]
        if isinstance(retry_context, RequestContext):
            retry_context.extensions["retry_attempt"] = 1
            retry_context.extensions["is_retry"] = True
        result = await callback(
            request=kwargs["request"],
            stream=kwargs["is_streaming"],
            allow_failover=False,
            context=retry_context,
        )
        return cast(ResponseEnvelope, result)

    deps["failover_executor"].apply_failure_recovery = AsyncMock(
        side_effect=_apply_failure_recovery
    )

    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="auxiliary retry call")],
    )
    context = _build_context(a_session_id)
    context.extensions.update(
        {
            "auxiliary_request": True,
            "auxiliary_root_session_id": a_session_id,
            "auxiliary_purpose": auxiliary_purpose,
            "auxiliary_operation_key": operation_key,
        }
    )

    result = await flow.call_completion(
        request=request,
        stream=False,
        allow_failover=True,
        context=context,
    )

    assert isinstance(result, ResponseEnvelope)
    allocator.allocate.assert_not_awaited()

    prepared_calls = deps["request_preparer"].prepare_backend_kwargs.call_args_list
    outbound_session_ids = [
        call.kwargs["session_id_for_backend"] for call in prepared_calls
    ]
    expected_first = build_auxiliary_effective_session_id(
        root_session_id=a_session_id,
        purpose=auxiliary_purpose,
        operation_key=operation_key,
        attempt_ordinal=1,
    )
    expected_second = build_auxiliary_effective_session_id(
        root_session_id=a_session_id,
        purpose=auxiliary_purpose,
        operation_key=operation_key,
        attempt_ordinal=2,
    )
    assert outbound_session_ids == [expected_first, expected_second]


@pytest.mark.asyncio
async def test_connector_wait_window_preserves_b2bua_identity_isolation() -> None:
    a_session_id = "llm-b2bua-a-8100"
    allocation = BlegAllocation(b_session_id="llm-b2bua-b-8100-1", seq=1)
    allocator = MagicMock()
    allocator.allocate = AsyncMock(return_value=allocation)

    observed_context_snapshots: list[tuple[str | None, str | None, str | None]] = []

    async def _connector_with_wait(**kwargs: Any) -> ResponseEnvelope:
        invoke_context = kwargs.get("context")
        identity = getattr(invoke_context, "b2bua_identity", None)
        observed_context_snapshots.append(
            (
                getattr(invoke_context, "session_id", None),
                getattr(identity, "a_session_id", None),
                getattr(identity, "b_session_id", None),
            )
        )
        # Simulate connector-internal hold/wait window before producing response.
        await asyncio.sleep(0)
        identity_after_wait = getattr(invoke_context, "b2bua_identity", None)
        observed_context_snapshots.append(
            (
                getattr(invoke_context, "session_id", None),
                getattr(identity_after_wait, "a_session_id", None),
                getattr(identity_after_wait, "b_session_id", None),
            )
        )
        return ResponseEnvelope(content={"ok": True}, headers={})

    flow, deps = _build_flow(
        a_session_id=a_session_id,
        allocator=allocator,
        connector_side_effect=_connector_with_wait,
    )

    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hold-window test")],
    )
    context = _build_context(a_session_id)

    result = await flow.call_completion(
        request=request,
        stream=False,
        allow_failover=False,
        context=context,
    )

    assert isinstance(result, ResponseEnvelope)
    allocator.allocate.assert_awaited_once()
    assert observed_context_snapshots == [
        (a_session_id, a_session_id, allocation.b_session_id),
        (a_session_id, a_session_id, allocation.b_session_id),
    ]

    kwargs_call = deps["request_preparer"].prepare_backend_kwargs.call_args.kwargs
    assert kwargs_call["session_id_for_backend"] == allocation.b_session_id
