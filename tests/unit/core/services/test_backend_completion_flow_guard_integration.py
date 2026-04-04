from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


@pytest.mark.asyncio
async def test_primary_streaming_path_wraps_with_backend_work_guard() -> None:
    availability_checker = MagicMock()
    availability_checker.check_backend_availability = AsyncMock()

    request_preparer = MagicMock()
    request_preparer.prepare_request = AsyncMock(
        return_value=MagicMock(
            backend="openai",
            model="gpt-4o-mini",
            uri_params={},
        )
    )
    request_preparer.synchronize_request_with_target = MagicMock(
        side_effect=lambda req, target: req
    )
    request_preparer.prepare_backend_request = AsyncMock(
        side_effect=lambda req, *_: req
    )
    request_preparer.prepare_backend_kwargs = MagicMock(return_value={})

    session_resolver = MagicMock()
    session_resolver.resolve_session = AsyncMock(return_value=(None, None))

    backend_invoker = MagicMock()
    backend_invoker.acquire_backend = AsyncMock(return_value=MagicMock())

    failover_executor = MagicMock()
    failover_executor.check_complex_failover = AsyncMock(return_value=False)

    wire_capture_orchestrator = MagicMock()
    wire_capture_orchestrator.prepare_wire_capture_context = AsyncMock(
        return_value=None
    )
    wire_capture_orchestrator.capture_wire_outbound = AsyncMock()
    wire_capture_orchestrator.detect_key_name = MagicMock(return_value=None)
    wire_capture_orchestrator.wrap_inbound_stream.side_effect = lambda **kwargs: kwargs[
        "stream"
    ]

    usage_accounting_orchestrator = MagicMock()
    usage_accounting_orchestrator.calculate_and_record_usage = AsyncMock(
        return_value=(0, None, None)
    )
    usage_accounting_orchestrator.wrap_response_for_usage = AsyncMock(
        side_effect=lambda result, **kwargs: result
    )
    usage_accounting_orchestrator.handle_streaming_response = AsyncMock(
        side_effect=lambda result, **kwargs: result
    )

    exception_normalizer = MagicMock()
    exception_normalizer.normalize.side_effect = lambda exc, *_: exc

    async def _bytes_stream() -> AsyncIterator[bytes]:
        yield b"data: [DONE]\n\n"

    stream_formatting_service = MagicMock()
    stream_formatting_service.stream_as_sse_bytes = MagicMock(
        return_value=_bytes_stream()
    )

    async def _backend_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="hello", metadata={})
        yield ProcessedResponse(content="world", metadata={})

    connector_invoker = MagicMock()
    connector_invoker.invoke = AsyncMock(
        return_value=StreamingResponseEnvelope(content=_backend_stream())
    )

    backend_work_guard = MagicMock()
    backend_work_guard.ensure_session_active.return_value = SessionKey(
        protocol="http",
        primary_id="req-flow-guard",
    )
    backend_work_guard.wrap_stream_with_cancellation.side_effect = (
        lambda *, stream, **kwargs: stream
    )

    flow = BackendCompletionFlow(
        availability_checker=availability_checker,
        request_preparer=request_preparer,
        session_resolver=session_resolver,
        backend_invoker=backend_invoker,
        failover_executor=failover_executor,
        wire_capture_orchestrator=wire_capture_orchestrator,
        usage_accounting_orchestrator=usage_accounting_orchestrator,
        exception_normalizer=exception_normalizer,
        stream_formatting_service=stream_formatting_service,
        connector_invoker=connector_invoker,
        backend_work_guard=backend_work_guard,
    )

    request = CanonicalChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="test")],
        stream=True,
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="req-flow-guard",
        session_id="sess-flow-guard",
    )

    result = await flow.call_completion(
        request=request,
        stream=True,
        allow_failover=False,
        context=context,
    )

    assert isinstance(result, StreamingResponseEnvelope)
    backend_work_guard.ensure_session_active.assert_called()
    backend_work_guard.wrap_stream_with_cancellation.assert_called_once()
    wrap_call = backend_work_guard.wrap_stream_with_cancellation.call_args.kwargs
    assert wrap_call["purpose"] == "primary_completion"
