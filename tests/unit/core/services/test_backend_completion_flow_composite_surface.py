from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


def _request() -> ChatRequest:
    return ChatRequest(
        model="gpt-4o",
        messages=[ChatMessage(role="user", content="hello")],
        extra_body={},
    )


def _context(call_purpose: str | None) -> RequestContext:
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id=f"req-{call_purpose or 'main'}",
    )
    if call_purpose is not None:
        context.extensions["call_purpose"] = call_purpose
    return context


def _build_flow(captured_surfaces: list[str | None]) -> BackendCompletionFlow:
    availability_checker = MagicMock()
    availability_checker.check_backend_availability = AsyncMock()

    request_preparer = MagicMock()

    async def _prepare_request(_request: ChatRequest, context: RequestContext | None):
        surface = (
            None
            if context is None
            else cast(str | None, context.extensions.get("composite_routing_surface"))
        )
        captured_surfaces.append(surface)
        return ResolvedTarget(backend="openai", model="gpt-4o", uri_params={})

    request_preparer.prepare_request = AsyncMock(side_effect=_prepare_request)
    request_preparer.synchronize_request_with_target = MagicMock(
        side_effect=lambda request, _target: request
    )
    request_preparer.prepare_backend_request = AsyncMock(
        side_effect=lambda request, *_args, **_kwargs: request
    )
    request_preparer.prepare_backend_kwargs = MagicMock(return_value={})

    session_resolver = MagicMock()
    session_resolver.resolve_session = AsyncMock(return_value=(None, None))

    backend_invoker = MagicMock()
    backend_invoker.acquire_backend = AsyncMock(return_value=MagicMock())

    failover_executor = MagicMock()
    failover_executor.check_complex_failover = AsyncMock(return_value=False)
    failover_executor.apply_failure_recovery = AsyncMock()

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
    connector_invoker.invoke = AsyncMock(
        return_value=ResponseEnvelope(content={"ok": True})
    )

    return BackendCompletionFlow(
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call_purpose", "expected_surface"),
    [
        (None, "main"),
        ("auxiliary", "auxiliary"),
        ("quality_verifier", "quality_verifier"),
        ("model_replacement", "replacement_bridge"),
    ],
)
async def test_call_completion_tags_context_with_composite_surface(
    call_purpose: str | None, expected_surface: str
) -> None:
    captured_surfaces: list[str | None] = []
    flow = _build_flow(captured_surfaces)

    await flow.call_completion(
        request=_request(),
        context=_context(call_purpose),
        allow_failover=False,
    )

    assert captured_surfaces == [expected_surface]
