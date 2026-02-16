from __future__ import annotations

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.services.b2bua_bleg_allocator_service import B2buaBlegAllocator
from src.core.services.b2bua_mapping_store_service import InMemoryB2buaMappingStore
from src.core.services.b2bua_session_id_factory import B2BUASessionIdFactory
from src.core.services.backend_completion_flow.service import BackendCompletionFlow
from src.core.services.cbor_wire_capture_service import CborWireCaptureService
from src.core.services.connector_invoker import ConnectorInvoker
from src.core.adapters.response_adapters import to_fastapi_response


def _with_b2bua_enabled(config: AppConfig) -> AppConfig:
    b2bua_config = config.session.b2bua.model_copy(
        update={"enabled": True, "echo_enabled": True}
    )
    session_config = config.session.model_copy(update={"b2bua": b2bua_config})
    return config.model_copy(update={"session": session_config})


def _build_flow(
    *,
    a_session_id: str,
    allocator: B2buaBlegAllocator,
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


@pytest.mark.asyncio
async def test_failover_produces_multiple_b_legs_under_one_a_leg() -> None:
    a_session_id = "llm-b2bua-123e4567-e89b-12d3-a456-426614174000"
    mapping_store = InMemoryB2buaMappingStore(
        continuity_ttl_seconds=3600,
        sliding_expiration=True,
        max_entries=128,
    )
    continuity = await mapping_store.resolve_or_create_a_session_id(
        auth_scope_id="scope-alpha",
        client_session_id="client-42",
        create_a_session_id=lambda: a_session_id,
    )
    assert continuity.a_session_id == a_session_id
    allocator = B2buaBlegAllocator(
        mapping_store=mapping_store,
        session_id_factory=B2BUASessionIdFactory(),
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
        return cast(
            ResponseEnvelope,
            await callback(
                request=kwargs["request"],
                stream=kwargs["is_streaming"],
                allow_failover=False,
                context=kwargs["context"],
            ),
        )

    deps["failover_executor"].apply_failure_recovery = AsyncMock(
        side_effect=_apply_failure_recovery
    )

    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="retry integration path")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=MagicMock(),
        request_id="req-failover",
        session_id=a_session_id,
        b2bua_identity=B2buaIdentity(
            a_session_id=a_session_id,
            auth_scope_id="scope-alpha",
            client_session_id="client-42",
        ),
    )

    result = await flow.call_completion(
        request=request,
        stream=False,
        allow_failover=True,
        context=context,
    )
    assert isinstance(result, ResponseEnvelope)

    records = await mapping_store.get_attempt_records(a_session_id)
    assert [record.seq for record in records] == [1, 2]
    assert all(record.a_session_id == a_session_id for record in records)
    assert len({record.b_session_id for record in records}) == 2


@pytest.mark.asyncio
async def test_observability_emits_a_and_b_ids_without_outbound_leakage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    a_session_id = "llm-b2bua-123e4567-e89b-12d3-a456-426614174111"
    b_session_id = "llm-b2bua-b-123e4567-e89b-12d3-a456-426614174111-7"
    config = _with_b2bua_enabled(AppConfig.from_env())
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=SimpleNamespace(config=config),
        request_id="req-observability",
        session_id=a_session_id,
        b2bua_identity=B2buaIdentity(
            a_session_id=a_session_id,
            b_session_id=b_session_id,
            auth_scope_id="scope-observability",
            client_session_id="client-observability",
            b_seq=7,
        ),
    )

    response = to_fastapi_response(
        ResponseEnvelope(content={"ok": True}, media_type="application/json"),
        context=context,
    )
    assert response.headers.get("x-b2bua-session-id") == a_session_id

    projected = ConnectorInvoker()._project_context(context)
    assert projected is not None
    assert projected.session_id == b_session_id
    assert projected.extensions is not None
    assert "a_session_id" not in projected.extensions
    assert "client_session_id" not in projected.extensions
    assert "auth_scope_id" not in projected.extensions
    b2bua_extension = projected.extensions.get("b2bua")
    assert isinstance(b2bua_extension, dict)
    assert b2bua_extension.get("b_seq") == 7

    with TemporaryDirectory() as tmpdir:
        capture_service = CborWireCaptureService(
            config=config,
            capture_dir=Path(tmpdir),
            session_id="capture-integration",
        )
        metadata = capture_service._extract_context_metadata(
            context=context,
            session_id=None,
            backend="openai",
            model="gpt-4",
            key_name="integration-key",
        )
        assert metadata.session_id == a_session_id
        assert metadata.a_session_id == a_session_id
        assert metadata.b_session_id == b_session_id
        assert metadata.b_seq == 7
        await capture_service.shutdown()

    mapping_store = InMemoryB2buaMappingStore()
    await mapping_store.resolve_or_create_a_session_id(
        auth_scope_id="scope-observability",
        client_session_id="client-observability",
        create_a_session_id=lambda: a_session_id,
    )
    flow, _deps = _build_flow(
        a_session_id=a_session_id,
        allocator=B2buaBlegAllocator(
            mapping_store=mapping_store,
            session_id_factory=B2BUASessionIdFactory(),
        ),
    )

    with caplog.at_level(
        logging.INFO,
        logger="src.core.services.backend_completion_flow.service",
    ):
        await flow.call_completion(
            request=CanonicalChatRequest(
                model="gpt-4",
                messages=[ChatMessage(role="user", content="emit log context")],
            ),
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
    assert getattr(record, "b_session_id", None) is not None
    assert getattr(record, "b_seq", None) is not None


@pytest.mark.asyncio
async def test_auxiliary_fail_open_preserves_isolated_identity_without_a_leg_leakage() -> (
    None
):
    a_session_id = "llm-b2bua-a-aux-9001"
    allocator = MagicMock()
    allocator.allocate = AsyncMock(side_effect=RuntimeError("allocator unavailable"))

    flow, deps = _build_flow(
        a_session_id=a_session_id,
        allocator=cast(B2buaBlegAllocator, allocator),
    )
    connector_facing_session_ids: list[str] = []

    def _prepare_backend_kwargs(**kwargs: Any) -> dict[str, str]:
        context = kwargs.get("context")
        extensions = getattr(context, "extensions", None)
        if isinstance(extensions, dict) and bool(extensions.get("auxiliary_request")):
            auxiliary_session_id = extensions.get("auxiliary_effective_session_id")
            if isinstance(auxiliary_session_id, str) and auxiliary_session_id:
                connector_facing_session_ids.append(auxiliary_session_id)
                return {"session_id": auxiliary_session_id}
        session_id_for_backend = kwargs.get("session_id_for_backend")
        if isinstance(session_id_for_backend, str) and session_id_for_backend:
            connector_facing_session_ids.append(session_id_for_backend)
            return {"session_id": session_id_for_backend}
        return {}

    deps["request_preparer"].prepare_backend_kwargs = MagicMock(
        side_effect=_prepare_backend_kwargs
    )

    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=MagicMock(),
        request_id="req-aux-fail-open",
        session_id=a_session_id,
        b2bua_identity=B2buaIdentity(
            a_session_id=a_session_id,
            auth_scope_id="scope-aux",
            client_session_id="client-aux",
        ),
    )
    context.extensions.update(
        {
            "auxiliary_request": True,
            "auxiliary_root_session_id": a_session_id,
            "auxiliary_purpose": "openai:gpt-4o-mini",
        }
    )
    request = CanonicalChatRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="Generate a short title")],
    )

    result = await flow.call_completion(
        request=request,
        stream=False,
        allow_failover=False,
        context=context,
    )
    assert isinstance(result, ResponseEnvelope)

    allocator.allocate.assert_not_awaited()
    auxiliary_effective_session_id = context.extensions.get(
        "auxiliary_effective_session_id"
    )
    assert isinstance(auxiliary_effective_session_id, str)
    assert auxiliary_effective_session_id.startswith("aux-")
    assert a_session_id not in auxiliary_effective_session_id

    kwargs_call = deps["request_preparer"].prepare_backend_kwargs.call_args.kwargs
    assert kwargs_call["session_id_for_backend"] == a_session_id
    assert connector_facing_session_ids[-1] == auxiliary_effective_session_id


@pytest.mark.asyncio
async def test_primary_allocator_fail_open_preserves_a_leg_without_connector_leakage() -> (
    None
):
    a_session_id = "llm-b2bua-a-primary-9002"
    allocator = MagicMock()
    allocator.allocate = AsyncMock(side_effect=RuntimeError("allocator unavailable"))

    flow, deps = _build_flow(
        a_session_id=a_session_id,
        allocator=cast(B2buaBlegAllocator, allocator),
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=MagicMock(),
        request_id="req-primary-fail-open",
        session_id=a_session_id,
        b2bua_identity=B2buaIdentity(
            a_session_id=a_session_id,
            auth_scope_id="scope-primary",
            client_session_id="client-primary",
        ),
    )
    context.extensions.update(
        {
            "a_session_id": "must-not-leak",
            "client_session_id": "must-not-leak",
            "auth_scope_id": "must-not-leak",
            "b2bua": {
                "a_session_id": "must-not-leak",
                "client_session_id": "must-not-leak",
                "auth_scope_id": "must-not-leak",
            },
        }
    )

    result = await flow.call_completion(
        request=CanonicalChatRequest(
            model="gpt-4o",
            messages=[ChatMessage(role="user", content="Primary fail-open check")],
        ),
        stream=False,
        allow_failover=False,
        context=context,
    )
    assert isinstance(result, ResponseEnvelope)

    allocator.allocate.assert_awaited_once()
    kwargs_call = deps["request_preparer"].prepare_backend_kwargs.call_args.kwargs
    assert kwargs_call["session_id_for_backend"] is None
    assert kwargs_call["context"].session_id == a_session_id

    projected = ConnectorInvoker()._project_context(
        deps["connector_invoker"].invoke.call_args.kwargs["context"]
    )
    assert projected is not None
    assert projected.session_id is None
    assert projected.extensions is not None
    assert "a_session_id" not in projected.extensions
    assert "client_session_id" not in projected.extensions
    assert "auth_scope_id" not in projected.extensions
    assert projected.extensions.get("b2bua") is None
