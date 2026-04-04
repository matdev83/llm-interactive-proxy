"""Integration tests for backend cancellation on client termination.

These tests verify that:
- Cancellation is scoped to a single lifecycle session
- Retry and failover are suppressed when session is cancelled
- In-flight backend work is cancelled
- Results are treated as non-deliverable after cancellation
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import SessionCancelledError
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.client_termination import ClientTerminationReason
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.services.backend_completion_flow.service import BackendCompletionFlow
from src.core.services.session_cancellation_coordinator import (
    SessionCancellationCoordinator,
)


class MockBackend:
    """Mock backend connector for testing."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def chat_completions(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        identity: Any | None = None,
        cancellation_token: SessionKey | None = None,
        **kwargs: Any,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Simulate backend call with optional delay."""
        self.calls.append(
            {
                "request_data": request_data,
                "effective_model": effective_model,
                "cancellation_token": cancellation_token,
            }
        )
        if self.delay > 0:
            await asyncio.sleep(self.delay)

        from src.core.domain.responses import ResponseEnvelope

        return ResponseEnvelope(
            content={"choices": [{"message": {"content": "test response"}}]},
            status_code=200,
        )


@pytest.fixture
def cancellation_coordinator() -> SessionCancellationCoordinator:
    """Create a cancellation coordinator for testing."""
    return SessionCancellationCoordinator(ttl_seconds=3600)


@pytest.fixture
def session_key_a() -> SessionKey:
    """Create a test session key for session A."""
    return SessionKey(protocol="http", primary_id="session-a", group_id="conv-1")


@pytest.fixture
def session_key_b() -> SessionKey:
    """Create a test session key for session B."""
    return SessionKey(protocol="http", primary_id="session-b", group_id="conv-1")


@pytest.fixture
def mock_backend() -> MockBackend:
    """Create a mock backend."""
    return MockBackend()


@pytest.fixture
def request_context_a(session_key_a: SessionKey) -> RequestContext:
    """Create a request context for session A."""
    headers = {}
    if session_key_a.group_id:
        headers["x-conversation-id"] = session_key_a.group_id
    return RequestContext(
        headers=headers,
        cookies={},
        state={},
        app_state=None,
        request_id=session_key_a.primary_id,
    )


@pytest.fixture
def request_context_b(session_key_b: SessionKey) -> RequestContext:
    """Create a request context for session B."""
    headers = {}
    if session_key_b.group_id:
        headers["x-conversation-id"] = session_key_b.group_id
    return RequestContext(
        headers=headers,
        cookies={},
        state={},
        app_state=None,
        request_id=session_key_b.primary_id,
    )


@pytest.fixture
def chat_request() -> ChatRequest:
    """Create a test chat request."""
    return CanonicalChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="test")],
        stream=False,
    )


@pytest.mark.asyncio
async def test_cancellation_scope_isolation(
    cancellation_coordinator: SessionCancellationCoordinator,
    session_key_a: SessionKey,
    session_key_b: SessionKey,
) -> None:
    """Test that cancelling session A does not affect session B."""
    # Cancel session A
    cancellation_coordinator.cancel_session(
        session_key_a, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    # Verify session A is cancelled
    assert cancellation_coordinator.is_cancelled(session_key_a) is True

    # Verify session B is not cancelled
    assert cancellation_coordinator.is_cancelled(session_key_b) is False

    # Verify ensure_not_cancelled raises for A but not B
    with pytest.raises(SessionCancelledError):
        cancellation_coordinator.ensure_not_cancelled(session_key_a)

    # Should not raise for B
    cancellation_coordinator.ensure_not_cancelled(session_key_b)


@pytest.mark.asyncio
async def test_cancellation_gate_prevents_backend_call(
    cancellation_coordinator: SessionCancellationCoordinator,
    session_key_a: SessionKey,
    request_context_a: RequestContext,
    chat_request: ChatRequest,
) -> None:
    """Test that cancellation gate prevents backend call initiation."""
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

    # Cancel session before backend call
    cancellation_coordinator.cancel_session(
        session_key_a, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    # Create mock collaborators
    mock_availability_checker = MagicMock(spec=IBackendAvailabilityChecker)
    mock_availability_checker.check_backend_availability = AsyncMock()

    mock_request_preparer = MagicMock(spec=IBackendRequestPreparer)
    mock_request_preparer.prepare_request = AsyncMock(
        return_value=MagicMock(backend="test", model="test-model", uri_params={})
    )
    mock_request_preparer.synchronize_request_with_target = MagicMock(
        return_value=chat_request
    )
    mock_request_preparer.prepare_backend_kwargs = MagicMock(return_value={})

    mock_session_resolver = MagicMock(spec=ICompletionSessionResolver)
    mock_session_resolver.resolve_session = AsyncMock(return_value=(None, "session-id"))

    mock_backend_invoker = MagicMock(spec=IBackendInvoker)
    mock_backend = MockBackend()
    mock_backend_invoker.acquire_backend = AsyncMock(return_value=mock_backend)

    mock_failover_executor = MagicMock(spec=IFailureRecoveryExecutor)
    mock_failover_executor.check_complex_failover = AsyncMock(return_value=False)

    mock_wire_capture = MagicMock(spec=IWireCaptureOrchestrator)
    mock_wire_capture.capture_wire_outbound = AsyncMock()
    mock_wire_capture.detect_key_name = MagicMock(return_value="test-key")
    mock_wire_capture.prepare_wire_capture_context = AsyncMock(return_value=None)
    mock_wire_capture.capture_inbound_response = AsyncMock()

    mock_usage_accounting = MagicMock(spec=IUsageAccountingOrchestrator)
    mock_usage_accounting.calculate_and_record_usage = AsyncMock(
        return_value=(0, None, None)
    )
    mock_usage_accounting.wrap_response_for_usage = AsyncMock(
        side_effect=lambda result, **kwargs: result
    )
    mock_usage_accounting.handle_non_streaming_response = AsyncMock(
        side_effect=lambda result, **kwargs: result
    )

    mock_exception_normalizer = MagicMock(spec=IExceptionNormalizer)

    mock_stream_formatting = MagicMock(spec=IStreamFormattingService)

    # Create BackendCompletionFlow with cancellation coordinator
    from src.core.services.connector_invoker import ConnectorInvoker

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
    )

    # Attempt to call completion - should raise SessionCancelledError
    with pytest.raises(SessionCancelledError):
        await flow.call_completion(
            request=chat_request,
            stream=False,
            allow_failover=False,
            context=request_context_a,
        )

    # Verify backend was never called
    assert len(mock_backend.calls) == 0


@pytest.mark.asyncio
async def test_retry_suppressed_on_cancellation(
    cancellation_coordinator: SessionCancellationCoordinator,
    session_key_a: SessionKey,
    request_context_a: RequestContext,
) -> None:
    """Test that retry is suppressed when session is cancelled."""
    from src.core.interfaces.configuration_interface import IConfig
    from src.core.interfaces.failover_planner_interface import IFailoverPlanner
    from src.core.services.backend_completion_flow.failure_recovery_executor import (
        FailureRecoveryExecutor,
    )

    # Cancel session
    cancellation_coordinator.cancel_session(
        session_key_a, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    # Create mock dependencies
    mock_failover_planner = MagicMock(spec=IFailoverPlanner)
    mock_config = MagicMock(spec=IConfig)

    executor = FailureRecoveryExecutor(
        failover_planner=mock_failover_planner,
        failure_handling_strategy=None,
        routing_service=None,
        config=mock_config,
        cancellation_coordinator=cancellation_coordinator,
    )

    # Attempt retry - should raise SessionCancelledError
    chat_request = CanonicalChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="test")],
        stream=False,
    )

    async def mock_callback(**kwargs: Any) -> ResponseEnvelope:
        return ResponseEnvelope(content={}, status_code=200)

    with pytest.raises(SessionCancelledError):
        await executor.execute_retry(
            request=chat_request,
            backend_type="test",
            wait_seconds=0.1,
            is_streaming=False,
            model="test-model",
            attempted_backends=[],
            call_completion_callback=mock_callback,
            context=request_context_a,
        )


@pytest.mark.asyncio
async def test_failover_suppressed_on_cancellation(
    cancellation_coordinator: SessionCancellationCoordinator,
    session_key_a: SessionKey,
    request_context_a: RequestContext,
) -> None:
    """Test that failover is suppressed when session is cancelled."""
    from src.core.interfaces.configuration_interface import IConfig
    from src.core.interfaces.failover_planner_interface import IFailoverPlanner
    from src.core.services.backend_completion_flow.failure_recovery_executor import (
        FailureRecoveryExecutor,
    )

    # Cancel session
    cancellation_coordinator.cancel_session(
        session_key_a, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    # Create mock dependencies
    mock_failover_planner = MagicMock(spec=IFailoverPlanner)
    mock_config = MagicMock(spec=IConfig)

    executor = FailureRecoveryExecutor(
        failover_planner=mock_failover_planner,
        failure_handling_strategy=None,
        routing_service=None,
        config=mock_config,
        cancellation_coordinator=cancellation_coordinator,
    )

    # Attempt failover - should raise SessionCancelledError
    chat_request = CanonicalChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="test")],
        stream=False,
    )

    async def mock_callback(**kwargs: Any) -> ResponseEnvelope:
        return ResponseEnvelope(content={}, status_code=200)

    with pytest.raises(SessionCancelledError):
        await executor.execute_failover(
            request=chat_request,
            next_backend="test-backend-2",
            is_streaming=False,
            backend_type="test-backend-1",
            model="test-model",
            call_completion_callback=mock_callback,
            context=request_context_a,
        )


@pytest.mark.asyncio
async def test_non_deliverable_result_after_cancellation(
    cancellation_coordinator: SessionCancellationCoordinator,
    session_key_a: SessionKey,
    request_context_a: RequestContext,
    chat_request: ChatRequest,
) -> None:
    """Test that results are treated as non-deliverable after cancellation."""
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

    # Create mock backend with small delay to allow cancellation during call
    mock_backend = MockBackend(delay=0.05)

    # Create mock collaborators
    mock_availability_checker = MagicMock(spec=IBackendAvailabilityChecker)
    mock_availability_checker.check_backend_availability = AsyncMock()

    mock_request_preparer = MagicMock(spec=IBackendRequestPreparer)
    mock_request_preparer.prepare_request = AsyncMock(
        return_value=MagicMock(backend="test", model="test-model", uri_params={})
    )
    mock_request_preparer.synchronize_request_with_target = MagicMock(
        return_value=chat_request
    )
    mock_request_preparer.prepare_backend_kwargs = MagicMock(return_value={})

    mock_session_resolver = MagicMock(spec=ICompletionSessionResolver)
    mock_session_resolver.resolve_session = AsyncMock(return_value=(None, "session-id"))

    mock_backend_invoker = MagicMock(spec=IBackendInvoker)
    mock_backend_invoker.acquire_backend = AsyncMock(return_value=mock_backend)

    mock_failover_executor = MagicMock(spec=IFailureRecoveryExecutor)
    mock_failover_executor.check_complex_failover = AsyncMock(return_value=False)

    mock_wire_capture = MagicMock(spec=IWireCaptureOrchestrator)
    mock_wire_capture.capture_wire_outbound = AsyncMock()
    mock_wire_capture.detect_key_name = MagicMock(return_value="test-key")
    mock_wire_capture.prepare_wire_capture_context = AsyncMock(return_value=None)
    mock_wire_capture.capture_inbound_response = AsyncMock()

    mock_usage_accounting = MagicMock(spec=IUsageAccountingOrchestrator)
    mock_usage_accounting.calculate_and_record_usage = AsyncMock(
        return_value=(0, None, None)
    )
    mock_usage_accounting.wrap_response_for_usage = AsyncMock(
        side_effect=lambda result, **kwargs: result
    )
    mock_usage_accounting.handle_non_streaming_response = AsyncMock(
        side_effect=lambda result, **kwargs: result
    )

    mock_exception_normalizer = MagicMock(spec=IExceptionNormalizer)
    mock_stream_formatting = MagicMock(spec=IStreamFormattingService)

    # Create BackendCompletionFlow with cancellation coordinator
    from src.core.services.connector_invoker import ConnectorInvoker

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
    )

    # Start backend call (it will complete quickly)
    call_task = asyncio.create_task(
        flow.call_completion(
            request=chat_request,
            stream=False,
            allow_failover=False,
            context=request_context_a,
        )
    )

    # Cancel session while backend call is in progress
    from tests.utils.fake_clock import FakeClockContext

    async with FakeClockContext() as clock:
        sleep_task1 = asyncio.create_task(asyncio.sleep(0.02))
        clock.advance(0.02)  # Small delay to let call start
        await sleep_task1
    cancellation_coordinator.cancel_session(
        session_key_a, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    # Wait for call to complete (backend has 0.05s delay, so this should be enough)
    async with FakeClockContext() as clock:
        sleep_task2 = asyncio.create_task(asyncio.sleep(0.1))
        clock.advance(0.1)
        await sleep_task2

    # Result should be treated as non-deliverable
    with pytest.raises(SessionCancelledError):
        await call_task


@pytest.mark.asyncio
async def test_empty_response_retry_suppressed_on_cancellation(
    cancellation_coordinator: SessionCancellationCoordinator,
    session_key_a: SessionKey,
    request_context_a: RequestContext,
) -> None:
    """Test that empty response retry is suppressed when session is cancelled."""
    from src.core.interfaces.backend_processor_interface import IBackendProcessor
    from src.core.interfaces.backend_request_manager_components import (
        IStructuredOutputEnforcer,
        IToolCallRetryCoordinator,
    )
    from src.core.interfaces.response_processor_interface import IResponseProcessor
    from src.core.services.backend_non_streaming_response_handler import (
        BackendNonStreamingResponseHandler,
    )
    from src.core.services.empty_response_middleware import EmptyResponseRetryError

    # Cancel session before retry
    cancellation_coordinator.cancel_session(
        session_key_a, ClientTerminationReason.CLIENT_DISCONNECTED
    )

    # Create mock dependencies
    mock_response_processor = MagicMock(spec=IResponseProcessor)
    # Make response processor raise EmptyResponseRetryError
    chat_request = CanonicalChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="test")],
        stream=False,
    )

    empty_error = EmptyResponseRetryError(
        recovery_prompt="recovery",
        session_id="session-id",
        retry_count=1,
        original_request=chat_request,
    )

    async def process_response_side_effect(*args: Any, **kwargs: Any) -> Any:
        raise empty_error

    mock_response_processor.process_response = AsyncMock(
        side_effect=process_response_side_effect
    )

    mock_structured_output_enforcer = MagicMock(spec=IStructuredOutputEnforcer)
    mock_tool_call_retry_coordinator = MagicMock(spec=IToolCallRetryCoordinator)
    mock_backend_processor = MagicMock(spec=IBackendProcessor)

    from src.core.interfaces.application_state_interface import IApplicationState

    mock_app_state = MagicMock(spec=IApplicationState)

    handler = BackendNonStreamingResponseHandler(
        response_processor=mock_response_processor,
        structured_output_enforcer=mock_structured_output_enforcer,
        tool_call_retry_coordinator=mock_tool_call_retry_coordinator,
        backend_processor=mock_backend_processor,
        app_state=mock_app_state,
        cancellation_coordinator=cancellation_coordinator,
    )

    # Attempt to handle response that triggers empty response retry
    # Should raise SessionCancelledError before retry
    from src.core.domain.backend_request_manager.context_models import (
        ResponseProcessingContext,
    )
    from src.core.domain.responses import ResponseEnvelope

    response = ResponseEnvelope(content={}, status_code=200)
    processing_context = ResponseProcessingContext(
        session_id="session-id",
        backend_name=None,
        model_name=None,
        client_os=None,
        original_request=None,
        structured_output=None,
    )

    # Handler should check cancellation before retry and raise SessionCancelledError
    with pytest.raises(SessionCancelledError):
        await handler.handle(
            response=response,
            request=chat_request,
            context=request_context_a,
            processing_context=processing_context,
        )

    # Verify backend processor was never called for retry
    mock_backend_processor.process_backend_request.assert_not_called()
