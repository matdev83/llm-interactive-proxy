"""Regression tests for duplicate EoS signal call bug.

This module contains regression tests to ensure that the bug where
record_error_termination was called twice (once by inner handler, once by outer handler)
when allow_failover=False is not reintroduced.

Bug: When allow_failover=False and an error occurred, both the inner exception handler
and the outer exception handler called record_error_termination, causing duplicate
signals and "already claimed" log messages.

Fix: Added marker pattern (__eos_recorded_by_inner_handler__) similar to
__handled_by_inner_handler__ to prevent duplicate calls.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from src.core.common.exceptions import BackendError
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.services.backend_completion_flow.eos_adapter import (
    BackendCompletionFlowEosAdapter,
)
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


@pytest.fixture
def mock_eos_adapter() -> MagicMock:
    """Create a mock EoS adapter for testing."""
    mock = MagicMock(spec=BackendCompletionFlowEosAdapter)
    mock.record_error_termination = AsyncMock()
    return mock


@pytest.fixture
def harness_with_eos(mock_eos_adapter: MagicMock) -> BackendCompletionFlow:
    """Create BackendCompletionFlow harness with EoS adapter."""
    availability_checker = AsyncMock()
    availability_checker.check_backend_availability = AsyncMock(return_value=None)

    request_preparer = AsyncMock()
    request_preparer.prepare_request = AsyncMock(
        return_value=BackendTarget(
            backend="test-backend", model="test-model", uri_params={}
        )
    )
    request_preparer.synchronize_request_with_target = Mock(
        return_value=ChatRequest(
            messages=[ChatMessage(role="user", content="test")],
            model="test-model",
        )
    )
    request_preparer.prepare_backend_request = AsyncMock(
        return_value=ChatRequest(
            messages=[ChatMessage(role="user", content="test")],
            model="test-model",
        )
    )
    request_preparer.prepare_backend_kwargs = Mock(return_value={})

    session_resolver = AsyncMock()
    session_resolver.resolve_session = AsyncMock(
        return_value=(None, "test-session-123")
    )

    backend_invoker = AsyncMock()
    backend_mock = AsyncMock()
    backend_invoker.acquire_backend = AsyncMock(return_value=backend_mock)

    failover_executor = AsyncMock()
    failover_executor.check_complex_failover = AsyncMock(return_value=False)

    wire_capture_orchestrator = AsyncMock()
    wire_capture_orchestrator.detect_key_name = Mock(return_value=None)
    wire_capture_orchestrator.wrap_inbound_stream = Mock(return_value=None)

    usage_accounting = AsyncMock()
    usage_accounting.calculate_and_record_usage = AsyncMock(
        return_value=(10, "ctp", "ptb")
    )
    usage_accounting.handle_backend_error = AsyncMock()

    exception_normalizer = Mock()
    exception_normalizer.normalize = Mock(
        return_value=BackendError("Test error", backend_name="test-backend")
    )

    stream_formatting_service = AsyncMock()
    connector_invoker = AsyncMock()

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
        connector_invoker=connector_invoker,
        resilience_coordinator=None,
        eos_adapter=mock_eos_adapter,
    )

    return service


@pytest.mark.asyncio
async def test_no_duplicate_eos_calls_when_allow_failover_false(
    harness_with_eos: BackendCompletionFlow,
    mock_eos_adapter: MagicMock,
) -> None:
    """Regression test: record_error_termination should only be called once when allow_failover=False.

    Bug: When allow_failover=False and an error occurred, both the inner exception handler
    (line ~846) and the outer exception handler (line ~919) called record_error_termination,
    causing duplicate signals and "already claimed" log messages.

    Fix: Added marker pattern (__eos_recorded_by_inner_handler__) that the inner handler sets,
    and the outer handlers check before calling record_error_termination.

    This test verifies that:
    1. record_error_termination is called exactly once (by inner handler)
    2. The marker is set on the exception
    3. The outer handler respects the marker and doesn't call it again
    """
    # Setup: Make backend call fail
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="test")],
        model="test-model",
    )
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        session_id="test-session-123",
        request_id="req-456",
    )

    # Make connector invoker raise an error
    harness_with_eos._connector_invoker.invoke = AsyncMock(
        side_effect=BackendError("Backend call failed", backend_name="test-backend")
    )

    # Call with allow_failover=False to trigger the bug scenario
    with pytest.raises(BackendError):
        await harness_with_eos.call_completion(
            request=request,
            stream=False,
            allow_failover=False,
            context=context,
        )

    # Verify record_error_termination was called exactly once (by inner handler)
    assert mock_eos_adapter.record_error_termination.await_count == 1

    # Verify the call was made with correct arguments
    mock_eos_adapter.record_error_termination.assert_awaited_once()
    call_args = mock_eos_adapter.record_error_termination.call_args
    assert call_args.kwargs["session_id"] == "test-session-123"
    assert call_args.kwargs["backend_type"] == "test-backend"
    assert call_args.kwargs["context"] == context


@pytest.mark.asyncio
async def test_eos_marker_set_on_exception_when_allow_failover_false(
    harness_with_eos: BackendCompletionFlow,
    mock_eos_adapter: MagicMock,
) -> None:
    """Regression test: Verify that __eos_recorded_by_inner_handler__ marker is set.

    This test ensures that when allow_failover=False, the inner handler sets the marker
    on the exception to prevent the outer handler from calling record_error_termination again.
    """
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="test")],
        model="test-model",
    )
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        session_id="test-session-123",
        request_id="req-456",
    )

    # Make connector invoker raise an error
    harness_with_eos._connector_invoker.invoke = AsyncMock(
        side_effect=BackendError("Backend call failed", backend_name="test-backend")
    )

    # Track the exception that gets raised
    raised_exception = None
    try:
        await harness_with_eos.call_completion(
            request=request,
            stream=False,
            allow_failover=False,
            context=context,
        )
    except BackendError as e:
        raised_exception = e

    # Verify exception was raised
    assert raised_exception is not None

    # Verify the marker was set (this prevents outer handler from calling record_error_termination)
    assert hasattr(raised_exception, "__eos_recorded_by_inner_handler__")
    assert raised_exception.__eos_recorded_by_inner_handler__ is True  # type: ignore[attr-defined]
