from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock

import pytest
from src.core.common.exceptions import AuthenticationError, BackendError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


# Create a dummy exception with status_code to simulate transport exceptions
class DummyTransportError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class OrchestratorHarness:
    service: BackendCompletionFlow
    availability_checker: AsyncMock
    request_preparer: AsyncMock
    session_resolver: AsyncMock
    backend_invoker: AsyncMock
    failover_executor: AsyncMock
    wire_capture_orchestrator: AsyncMock
    usage_accounting: AsyncMock
    exception_normalizer: Mock


@pytest.fixture
def harness() -> OrchestratorHarness:
    availability_checker = AsyncMock()

    request_preparer = AsyncMock()
    request_preparer.prepare_request = AsyncMock()
    request_preparer.prepare_backend_request = AsyncMock()
    request_preparer.synchronize_request_with_target = Mock()
    request_preparer.prepare_backend_kwargs = Mock()

    session_resolver = AsyncMock()
    backend_invoker = AsyncMock()
    failover_executor = AsyncMock()

    wire_capture_orchestrator = AsyncMock()
    wire_capture_orchestrator.detect_key_name = Mock()
    wire_capture_orchestrator.wrap_inbound_stream = Mock()

    usage_accounting = AsyncMock()
    exception_normalizer = Mock()
    stream_formatting_service = AsyncMock()

    service = BackendCompletionFlow(
        availability_checker=availability_checker,
        request_preparer=request_preparer,
        session_resolver=session_resolver,
        backend_invoker=backend_invoker,
        failover_executor=failover_executor,
        wire_capture_orchestrator=wire_capture_orchestrator,
        usage_accounting_orchestrator=usage_accounting,
        exception_normalizer=exception_normalizer,
        stream_formatting_service=stream_formatting_service,
        resilience_coordinator=None,
    )

    return OrchestratorHarness(
        service=service,
        availability_checker=availability_checker,
        request_preparer=request_preparer,
        session_resolver=session_resolver,
        backend_invoker=backend_invoker,
        failover_executor=failover_executor,
        wire_capture_orchestrator=wire_capture_orchestrator,
        usage_accounting=usage_accounting,
        exception_normalizer=exception_normalizer,
    )


@pytest.mark.asyncio
async def test_normalizes_transport_exceptions(harness: OrchestratorHarness) -> None:
    """Verify that foreign exceptions are normalized to domain errors."""

    # Setup
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="test")],
        model="gpt-4",
    )
    context = RequestContext(headers={}, cookies={}, state=Mock(), app_state=Mock())

    # Mock preparer to return success
    harness.request_preparer.prepare_request.return_value = (
        "backend_a",
        "model_a",
        {},
    )
    harness.request_preparer.synchronize_request_with_target.return_value = request
    harness.failover_executor.check_complex_failover.return_value = False
    harness.availability_checker.check_backend_availability.return_value = None

    # Mock backend manager to succeed
    backend_mock = AsyncMock()
    harness.backend_invoker.acquire_backend.return_value = backend_mock

    # Mock preparer to return domain request
    harness.request_preparer.prepare_backend_request.return_value = request
    harness.request_preparer.prepare_backend_kwargs.return_value = {}
    harness.session_resolver.resolve_session.return_value = (None, "session_1")

    # Mock response handler calculate usage
    harness.usage_accounting.calculate_and_record_usage.return_value = (
        10,
        "ctp",
        "ptb",
    )

    # Mock backend call to raise transport error
    transport_error = DummyTransportError("Connection failed", 503)
    backend_mock.chat_completions.side_effect = transport_error

    # Mock exception normalizer to return domain error
    domain_error = BackendError(
        message="Connection failed", backend_name="backend_a", status_code=503
    )
    harness.exception_normalizer.normalize.return_value = domain_error

    # Mock response handler to re-raise normalized error
    async def side_effect_handle_backend_error(*args, **kwargs):
        pass  # Just pass

    harness.usage_accounting.handle_backend_error.side_effect = (
        side_effect_handle_backend_error
    )

    # Mock failover manager to raise the error
    async def raise_domain_error(*args, **kwargs):
        raise domain_error

    harness.failover_executor.apply_failure_recovery.side_effect = raise_domain_error

    # Execute
    with pytest.raises(BackendError) as excinfo:
        await harness.service.call_completion(
            request, allow_failover=True, context=context
        )

    # Verify normalization happened with the CORRECT error
    harness.exception_normalizer.normalize.assert_called_with(
        transport_error, "backend_a"
    )
    assert excinfo.value == domain_error


@pytest.mark.asyncio
async def test_auth_failure_invalidates_backend(harness: OrchestratorHarness) -> None:
    """Verify authentication failure triggers backend invalidation."""

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="test")],
        model="gpt-4",
    )
    context = RequestContext(headers={}, cookies={}, state=Mock(), app_state=Mock())

    # Mock setup
    harness.request_preparer.prepare_request.return_value = (
        "backend_a",
        "model_a",
        {},
    )
    harness.request_preparer.synchronize_request_with_target.return_value = request
    harness.failover_executor.check_complex_failover.return_value = False
    harness.availability_checker.check_backend_availability.return_value = None
    backend_mock = AsyncMock()
    harness.backend_invoker.acquire_backend.return_value = backend_mock
    harness.request_preparer.prepare_backend_request.return_value = request
    harness.request_preparer.prepare_backend_kwargs.return_value = {}
    harness.session_resolver.resolve_session.return_value = (None, "session_1")
    harness.usage_accounting.calculate_and_record_usage.return_value = (
        10,
        "ctp",
        "ptb",
    )

    # Backend raises auth error
    auth_error = DummyTransportError("Unauthorized", 401)
    backend_mock.chat_completions.side_effect = auth_error

    # Normalizer returns AuthenticationError
    domain_auth_error = AuthenticationError("Invalid key")
    harness.exception_normalizer.normalize.return_value = domain_auth_error

    # Mock response handler to raise the auth error
    async def raise_auth_error(*args, **kwargs):
        raise domain_auth_error

    harness.usage_accounting.handle_auth_failure.side_effect = raise_auth_error

    # Execute
    with pytest.raises(AuthenticationError):
        await harness.service.call_completion(
            request, allow_failover=True, context=context
        )

    # Verify
    harness.usage_accounting.handle_auth_failure.assert_called_once()
    call_args = harness.usage_accounting.handle_auth_failure.call_args
    # Check that normalized_exc (first positional arg) is the domain_auth_error
    # The exception_normalizer should have normalized the transport error to domain_auth_error
    assert call_args[0][0] == domain_auth_error


@pytest.mark.asyncio
async def test_captures_inbound_error_payload(harness: OrchestratorHarness) -> None:
    """Verify wire capture is invoked for errors."""

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="test")],
        model="gpt-4",
    )
    context = RequestContext(headers={}, cookies={}, state=Mock(), app_state=Mock())

    # Mock setup
    harness.request_preparer.prepare_request.return_value = (
        "backend_a",
        "model_a",
        {},
    )
    harness.request_preparer.synchronize_request_with_target.return_value = request
    harness.failover_executor.check_complex_failover.return_value = False
    harness.availability_checker.check_backend_availability.return_value = None

    backend_mock = AsyncMock()
    # Mock acquire_backend correctly
    harness.backend_invoker.acquire_backend.return_value = backend_mock
    harness.request_preparer.prepare_backend_request.return_value = request
    harness.request_preparer.prepare_backend_kwargs.return_value = {}
    harness.session_resolver.resolve_session.return_value = (None, "session_1")
    harness.usage_accounting.calculate_and_record_usage.return_value = (
        10,
        "ctp",
        "ptb",
    )

    # Backend raises error
    error = BackendError(message="Boom", backend_name="backend_a")
    backend_mock.chat_completions.side_effect = error

    harness.exception_normalizer.normalize.return_value = error

    # Response handler should handle backend error
    harness.usage_accounting.handle_backend_error.return_value = None

    # Failover raises error (use function side effect to ensure raise)
    async def raise_error(*args, **kwargs):
        raise error

    harness.failover_executor.apply_failure_recovery.side_effect = raise_error

    # Execute
    with pytest.raises(BackendError):
        await harness.service.call_completion(
            request, allow_failover=True, context=context
        )

    # Verify response handler called to handle error
    harness.usage_accounting.handle_backend_error.assert_called_once()
    args = harness.usage_accounting.handle_backend_error.call_args
    assert args[1]["call_exc"] == error


@pytest.mark.asyncio
async def test_records_usage_for_streaming(harness: OrchestratorHarness) -> None:
    """Verify usage tracking wrapper is applied for streaming responses."""

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="test")],
        model="gpt-4",
        stream=True,
    )
    context = RequestContext(headers={}, cookies={}, state=Mock(), app_state=Mock())

    # Mock setup
    harness.request_preparer.prepare_request.return_value = (
        "backend_a",
        "model_a",
        {},
    )
    harness.request_preparer.synchronize_request_with_target.return_value = request
    harness.failover_executor.check_complex_failover.return_value = False
    harness.availability_checker.check_backend_availability.return_value = None

    backend_mock = AsyncMock()
    harness.backend_invoker.acquire_backend.return_value = backend_mock
    harness.request_preparer.prepare_backend_request.return_value = request
    harness.request_preparer.prepare_backend_kwargs.return_value = {}
    harness.session_resolver.resolve_session.return_value = (None, "session_1")
    harness.usage_accounting.calculate_and_record_usage.return_value = (
        10,
        "ctp",
        "ptb",
    )

    # Streaming response
    streaming_response = StreamingResponseEnvelope(
        content=AsyncMock(), media_type="text/event-stream"
    )
    backend_mock.chat_completions.return_value = streaming_response

    # Response handler mocks
    harness.usage_accounting.wrap_response_for_usage.return_value = streaming_response
    harness.usage_accounting.handle_streaming_response.return_value = streaming_response

    # Execute
    result = await harness.service.call_completion(
        request, stream=True, allow_failover=True, context=context
    )

    # Verify usage wrapping was called
    harness.usage_accounting.wrap_response_for_usage.assert_called_once()
    assert result == streaming_response


@pytest.mark.asyncio
async def test_records_usage_for_non_streaming(harness: OrchestratorHarness) -> None:
    """Verify usage recording for non-streaming responses."""

    request = ChatRequest(
        messages=[ChatMessage(role="user", content="test")],
        model="gpt-4",
        stream=False,
    )
    context = RequestContext(headers={}, cookies={}, state=Mock(), app_state=Mock())

    # Mock setup
    harness.request_preparer.prepare_request.return_value = (
        "backend_a",
        "model_a",
        {},
    )
    harness.request_preparer.synchronize_request_with_target.return_value = request
    harness.failover_executor.check_complex_failover.return_value = False
    harness.availability_checker.check_backend_availability.return_value = None

    backend_mock = AsyncMock()
    harness.backend_invoker.acquire_backend.return_value = backend_mock
    harness.request_preparer.prepare_backend_request.return_value = request
    harness.request_preparer.prepare_backend_kwargs.return_value = {}
    harness.session_resolver.resolve_session.return_value = (None, "session_1")
    harness.usage_accounting.calculate_and_record_usage.return_value = (
        10,
        "ctp",
        "ptb",
    )

    # Non-streaming response
    response = ResponseEnvelope(content="hello")
    backend_mock.chat_completions.return_value = response

    # Response handler mocks
    harness.usage_accounting.wrap_response_for_usage.return_value = response
    harness.usage_accounting.handle_non_streaming_response.return_value = response

    # Execute
    result = await harness.service.call_completion(
        request, stream=False, allow_failover=True, context=context
    )

    # Verify usage wrapping and handling called
    harness.usage_accounting.wrap_response_for_usage.assert_called_once()
    harness.usage_accounting.handle_non_streaming_response.assert_called_once()
    assert result == response
