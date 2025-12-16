from unittest.mock import AsyncMock, Mock

import pytest
from src.core.common.exceptions import AuthenticationError, BackendError
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget
from tests.unit.core.services.backend_flow_test_helper import (
    create_test_backend_completion_flow,
)


# Create a dummy exception with status_code to simulate transport exceptions
class DummyTransportError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


@pytest.fixture
def mock_deps():
    backend_lifecycle_manager = Mock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    backend_lifecycle_manager.get_active_backends.return_value = {}

    return {
        "backend_model_resolver": AsyncMock(),
        "stream_session_id_resolver": AsyncMock(),
        "failover_planner": AsyncMock(),
        "session_service": AsyncMock(),
        "backend_lifecycle_manager": backend_lifecycle_manager,
        "backend_config_service": AsyncMock(),
        "reasoning_config_applicator": Mock(),
        "uri_parameter_applicator": Mock(),
        "stream_formatting_service": AsyncMock(),
        "usage_tracking_wrapper": AsyncMock(),
        "exception_normalizer": Mock(),
        "planning_phase_manager": AsyncMock(),
        "backend_factory": AsyncMock(),
        "config": Mock(),
        "app_state": Mock(),
        "failover_coordinator": AsyncMock(),
        "wire_capture": AsyncMock(),
        "usage_tracking_service": AsyncMock(),
        "resilience_coordinator": Mock(),
        "failure_handling_strategy": Mock(),
        "routing_service": Mock(),
        "failover_routes": {},
    }


@pytest.fixture
def orchestrator(mock_deps):
    # Setup mocks for model resolver
    mock_deps["backend_model_resolver"].resolve_target = AsyncMock(
        return_value=ResolvedTarget(backend="backend_a", model="model_a", uri_params={})
    )
    mock_deps["backend_model_resolver"].synchronize_request_with_target = Mock(
        side_effect=lambda r, t: r
    )
    mock_deps["reasoning_config_applicator"].apply = Mock(side_effect=lambda r, s: r)
    mock_deps["uri_parameter_applicator"].apply = Mock(side_effect=lambda r, u, b, s: r)
    mock_deps["backend_lifecycle_manager"].get_disabled_backends.return_value = {}
    # Don't set a default side_effect for normalize - let tests override it

    service = create_test_backend_completion_flow(mock_deps)
    # Mock internal collaborators for test control
    service._request_preparer = AsyncMock()
    # IMPORTANT: synchronize_request_with_target and prepare_backend_kwargs are synchronous methods
    service._request_preparer.synchronize_request_with_target = Mock()
    service._request_preparer.prepare_backend_kwargs = Mock()
    service._session_resolver = AsyncMock()
    service._backend_invoker = AsyncMock()
    service._failover_executor = AsyncMock()
    service._wire_capture_orchestrator = AsyncMock()
    service._usage_accounting = AsyncMock()
    service._exception_normalizer = mock_deps["exception_normalizer"]

    return service


@pytest.mark.asyncio
async def test_normalizes_transport_exceptions(orchestrator, mock_deps):
    """Verify that foreign exceptions are normalized to domain errors."""

    # Setup
    request = ChatRequest(messages=[{"role": "user", "content": "test"}], model="gpt-4")
    context = RequestContext(headers={}, cookies={}, state=Mock(), app_state=Mock())

    # Mock preparer to return success
    orchestrator._request_preparer.prepare_request.return_value = (
        "backend_a",
        "model_a",
        {},
    )
    orchestrator._request_preparer.synchronize_request_with_target.return_value = (
        request
    )
    orchestrator._failover_executor.check_complex_failover.return_value = False

    # Mock backend manager to succeed
    backend_mock = AsyncMock()
    orchestrator._backend_invoker.acquire_backend.return_value = backend_mock

    # Mock preparer to return domain request
    orchestrator._request_preparer.prepare_backend_request.return_value = request
    orchestrator._request_preparer.prepare_backend_kwargs.return_value = {}
    orchestrator._session_resolver.resolve_session.return_value = (None, "session_1")

    # Mock response handler calculate usage
    orchestrator._usage_accounting.calculate_and_record_usage.return_value = (
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
    orchestrator._exception_normalizer.normalize.return_value = domain_error

    # Mock response handler to re-raise normalized error
    async def side_effect_handle_backend_error(*args, **kwargs):
        pass  # Just pass

    orchestrator._usage_accounting.handle_backend_error.side_effect = (
        side_effect_handle_backend_error
    )

    # Mock failover manager to raise the error
    async def raise_domain_error(*args, **kwargs):
        raise domain_error

    orchestrator._failover_executor.apply_failure_recovery.side_effect = (
        raise_domain_error
    )

    # Execute
    with pytest.raises(BackendError) as excinfo:
        await orchestrator.call_completion(
            request, allow_failover=True, context=context
        )

    # Verify normalization happened with the CORRECT error
    orchestrator._exception_normalizer.normalize.assert_called_with(
        transport_error, "backend_a"
    )
    assert excinfo.value == domain_error


@pytest.mark.asyncio
async def test_auth_failure_invalidates_backend(orchestrator, mock_deps):
    """Verify authentication failure triggers backend invalidation."""

    request = ChatRequest(messages=[{"role": "user", "content": "test"}], model="gpt-4")
    context = RequestContext(headers={}, cookies={}, state=Mock(), app_state=Mock())

    # Mock setup
    orchestrator._request_preparer.prepare_request.return_value = (
        "backend_a",
        "model_a",
        {},
    )
    orchestrator._request_preparer.synchronize_request_with_target.return_value = (
        request
    )
    orchestrator._failover_executor.check_complex_failover.return_value = False
    backend_mock = AsyncMock()
    orchestrator._backend_invoker.acquire_backend.return_value = backend_mock
    orchestrator._request_preparer.prepare_backend_request.return_value = request
    orchestrator._request_preparer.prepare_backend_kwargs.return_value = {}
    orchestrator._session_resolver.resolve_session.return_value = (None, "session_1")
    orchestrator._usage_accounting.calculate_and_record_usage.return_value = (
        10,
        "ctp",
        "ptb",
    )

    # Backend raises auth error
    auth_error = DummyTransportError("Unauthorized", 401)
    backend_mock.chat_completions.side_effect = auth_error

    # Normalizer returns AuthenticationError
    domain_auth_error = AuthenticationError("Invalid key")
    orchestrator._exception_normalizer.normalize.return_value = domain_auth_error

    # Mock response handler to raise the auth error
    async def raise_auth_error(*args, **kwargs):
        raise domain_auth_error

    orchestrator._usage_accounting.handle_auth_failure.side_effect = raise_auth_error

    # Execute
    with pytest.raises(AuthenticationError):
        await orchestrator.call_completion(
            request, allow_failover=True, context=context
        )

    # Verify
    orchestrator._usage_accounting.handle_auth_failure.assert_called_once()
    call_args = orchestrator._usage_accounting.handle_auth_failure.call_args
    # Check that normalized_exc (first positional arg) is the domain_auth_error
    # The exception_normalizer should have normalized the transport error to domain_auth_error
    assert call_args[0][0] == domain_auth_error


@pytest.mark.asyncio
async def test_captures_inbound_error_payload(orchestrator, mock_deps):
    """Verify wire capture is invoked for errors."""

    request = ChatRequest(messages=[{"role": "user", "content": "test"}], model="gpt-4")
    context = RequestContext(headers={}, cookies={}, state=Mock(), app_state=Mock())

    # Mock setup
    orchestrator._request_preparer.prepare_request.return_value = (
        "backend_a",
        "model_a",
        {},
    )
    orchestrator._request_preparer.synchronize_request_with_target.return_value = (
        request
    )
    orchestrator._failover_executor.check_complex_failover.return_value = False

    backend_mock = AsyncMock()
    # Mock acquire_backend correctly
    orchestrator._backend_invoker.acquire_backend.return_value = backend_mock
    orchestrator._request_preparer.prepare_backend_request.return_value = request
    orchestrator._request_preparer.prepare_backend_kwargs.return_value = {}
    orchestrator._session_resolver.resolve_session.return_value = (None, "session_1")
    orchestrator._usage_accounting.calculate_and_record_usage.return_value = (
        10,
        "ctp",
        "ptb",
    )

    # Backend raises error
    error = BackendError(message="Boom", backend_name="backend_a")
    backend_mock.chat_completions.side_effect = error

    orchestrator._exception_normalizer.normalize.return_value = error

    # Response handler should handle backend error
    orchestrator._usage_accounting.handle_backend_error.return_value = None

    # Failover raises error (use function side effect to ensure raise)
    async def raise_error(*args, **kwargs):
        raise error

    orchestrator._failover_executor.apply_failure_recovery.side_effect = raise_error

    # Execute
    with pytest.raises(BackendError):
        await orchestrator.call_completion(
            request, allow_failover=True, context=context
        )

    # Verify response handler called to handle error
    orchestrator._usage_accounting.handle_backend_error.assert_called_once()
    args = orchestrator._usage_accounting.handle_backend_error.call_args
    assert args[1]["call_exc"] == error


@pytest.mark.asyncio
async def test_records_usage_for_streaming(orchestrator, mock_deps):
    """Verify usage tracking wrapper is applied for streaming responses."""

    request = ChatRequest(
        messages=[{"role": "user", "content": "test"}], model="gpt-4", stream=True
    )
    context = RequestContext(headers={}, cookies={}, state=Mock(), app_state=Mock())

    # Mock setup
    orchestrator._request_preparer.prepare_request.return_value = (
        "backend_a",
        "model_a",
        {},
    )
    orchestrator._request_preparer.synchronize_request_with_target.return_value = (
        request
    )
    orchestrator._failover_executor.check_complex_failover.return_value = False

    backend_mock = AsyncMock()
    orchestrator._backend_invoker.acquire_backend.return_value = backend_mock
    orchestrator._request_preparer.prepare_backend_request.return_value = request
    orchestrator._request_preparer.prepare_backend_kwargs.return_value = {}
    orchestrator._session_resolver.resolve_session.return_value = (None, "session_1")
    orchestrator._usage_accounting.calculate_and_record_usage.return_value = (
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
    orchestrator._usage_accounting.wrap_response_for_usage.return_value = (
        streaming_response
    )
    orchestrator._usage_accounting.handle_streaming_response.return_value = (
        streaming_response
    )

    # Execute
    result = await orchestrator.call_completion(
        request, stream=True, allow_failover=True, context=context
    )

    # Verify usage wrapping was called
    orchestrator._usage_accounting.wrap_response_for_usage.assert_called_once()
    assert result == streaming_response


@pytest.mark.asyncio
async def test_records_usage_for_non_streaming(orchestrator, mock_deps):
    """Verify usage recording for non-streaming responses."""

    request = ChatRequest(
        messages=[{"role": "user", "content": "test"}], model="gpt-4", stream=False
    )
    context = RequestContext(headers={}, cookies={}, state=Mock(), app_state=Mock())

    # Mock setup
    orchestrator._request_preparer.prepare_request.return_value = (
        "backend_a",
        "model_a",
        {},
    )
    orchestrator._request_preparer.synchronize_request_with_target.return_value = (
        request
    )
    orchestrator._failover_executor.check_complex_failover.return_value = False

    backend_mock = AsyncMock()
    orchestrator._backend_invoker.acquire_backend.return_value = backend_mock
    orchestrator._request_preparer.prepare_backend_request.return_value = request
    orchestrator._request_preparer.prepare_backend_kwargs.return_value = {}
    orchestrator._session_resolver.resolve_session.return_value = (None, "session_1")
    orchestrator._usage_accounting.calculate_and_record_usage.return_value = (
        10,
        "ctp",
        "ptb",
    )

    # Non-streaming response
    response = ResponseEnvelope(content="hello")
    backend_mock.chat_completions.return_value = response

    # Response handler mocks
    orchestrator._usage_accounting.wrap_response_for_usage.return_value = response
    orchestrator._usage_accounting.handle_non_streaming_response.return_value = response

    # Execute
    result = await orchestrator.call_completion(
        request, stream=False, allow_failover=True, context=context
    )

    # Verify usage wrapping and handling called
    orchestrator._usage_accounting.wrap_response_for_usage.assert_called_once()
    orchestrator._usage_accounting.handle_non_streaming_response.assert_called_once()
    assert result == response
