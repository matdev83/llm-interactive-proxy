"""Integration regression for primary-stream cancellation via BackendWorkGuard."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.client_termination import ClientTerminationReason
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_completion_flow.service import BackendCompletionFlow
from src.core.services.backend_work_guard import BackendWorkGuard
from src.core.services.connector_invoker import ConnectorInvoker
from src.core.services.session_cancellation_coordinator import (
    SessionCancellationCoordinator,
)


class _StreamingMockBackend:
    async def chat_completions(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,
        cancellation_token: SessionKey | None = None,
        **kwargs: Any,
    ) -> StreamingResponseEnvelope:
        async def _stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(content="first", metadata={})
            yield ProcessedResponse(content="second", metadata={})

        return StreamingResponseEnvelope(content=_stream())


@pytest.mark.asyncio
async def test_primary_streaming_stops_after_session_cancellation() -> None:
    cancellation_coordinator = SessionCancellationCoordinator(ttl_seconds=3600)
    session_key = SessionKey(
        protocol="http",
        primary_id="session-stream-guard",
        group_id="conv-stream-guard",
    )
    request_context = RequestContext(
        headers={"x-conversation-id": "conv-stream-guard"},
        cookies={},
        state={},
        app_state=None,
        request_id="session-stream-guard",
    )

    from src.core.interfaces.backend_completion_collaborators import (
        IBackendAvailabilityChecker,
        IBackendInvoker,
        IBackendRequestPreparer,
        ICompletionSessionResolver,
        IFailureRecoveryExecutor,
        IUsageAccountingOrchestrator,
        IWireCaptureOrchestrator,
    )
    from src.core.interfaces.exception_normalizer_interface import IExceptionNormalizer
    from src.core.interfaces.stream_formatting_interface import IStreamFormattingService

    mock_availability_checker = MagicMock(spec=IBackendAvailabilityChecker)
    mock_availability_checker.check_backend_availability = AsyncMock()

    chat_request = CanonicalChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="test")],
        stream=True,
    )

    mock_request_preparer = MagicMock(spec=IBackendRequestPreparer)
    mock_request_preparer.prepare_request = AsyncMock(
        return_value=MagicMock(backend="test", model="test-model", uri_params={})
    )
    mock_request_preparer.synchronize_request_with_target = MagicMock(
        return_value=chat_request
    )
    mock_request_preparer.prepare_backend_request = AsyncMock(return_value=chat_request)
    mock_request_preparer.prepare_backend_kwargs = MagicMock(return_value={})

    mock_session_resolver = MagicMock(spec=ICompletionSessionResolver)
    mock_session_resolver.resolve_session = AsyncMock(return_value=(None, "session-id"))

    mock_backend_invoker = MagicMock(spec=IBackendInvoker)
    mock_backend_invoker.acquire_backend = AsyncMock(
        return_value=_StreamingMockBackend()
    )

    mock_failover_executor = MagicMock(spec=IFailureRecoveryExecutor)
    mock_failover_executor.check_complex_failover = AsyncMock(return_value=False)
    mock_failover_executor.apply_failure_recovery = AsyncMock()

    mock_wire_capture = MagicMock(spec=IWireCaptureOrchestrator)
    mock_wire_capture.capture_wire_outbound = AsyncMock()
    mock_wire_capture.detect_key_name = MagicMock(return_value="test-key")
    mock_wire_capture.prepare_wire_capture_context = AsyncMock(return_value=None)
    mock_wire_capture.capture_inbound_response = AsyncMock()
    mock_wire_capture.wrap_inbound_stream.side_effect = lambda **kwargs: kwargs[
        "stream"
    ]

    mock_usage_accounting = MagicMock(spec=IUsageAccountingOrchestrator)
    mock_usage_accounting.calculate_and_record_usage = AsyncMock(
        return_value=(0, None, None)
    )
    mock_usage_accounting.wrap_response_for_usage = AsyncMock(
        side_effect=lambda result, **kwargs: result
    )
    mock_usage_accounting.handle_streaming_response = AsyncMock(
        side_effect=lambda result, **kwargs: result
    )

    mock_exception_normalizer = MagicMock(spec=IExceptionNormalizer)
    mock_stream_formatting = MagicMock(spec=IStreamFormattingService)

    def _to_sse_bytes(stream: AsyncIterator[ProcessedResponse]) -> AsyncIterator[bytes]:
        async def _inner() -> AsyncIterator[bytes]:
            async for chunk in stream:
                payload = {
                    "choices": [
                        {
                            "delta": {"content": str(getattr(chunk, "content", ""))},
                            "finish_reason": None,
                        }
                    ]
                }
                yield f"data: {json.dumps(payload)}\n\n".encode()

        return _inner()

    mock_stream_formatting.stream_as_sse_bytes.side_effect = _to_sse_bytes

    flow = BackendCompletionFlow(
        availability_checker=mock_availability_checker,
        request_preparer=mock_request_preparer,
        session_resolver=mock_session_resolver,
        backend_invoker=mock_backend_invoker,
        failover_executor=mock_failover_executor,
        wire_capture_orchestrator=mock_wire_capture,
        usage_accounting_orchestrator=mock_usage_accounting,
        exception_normalizer=mock_exception_normalizer,
        stream_formatting_service=mock_stream_formatting,
        connector_invoker=ConnectorInvoker(),
        cancellation_coordinator=cancellation_coordinator,
        backend_work_guard=BackendWorkGuard(cancellation_coordinator),
    )

    result = await flow.call_completion(
        request=chat_request,
        stream=True,
        allow_failover=False,
        context=request_context,
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None

    iterator = result.content.__aiter__()
    first_chunk = await anext(iterator)
    assert "first" in str(first_chunk.content)

    cancellation_coordinator.cancel_session(
        session_key, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    remaining_chunks = [chunk async for chunk in iterator]
    assert remaining_chunks == []
    mock_failover_executor.apply_failure_recovery.assert_not_called()
