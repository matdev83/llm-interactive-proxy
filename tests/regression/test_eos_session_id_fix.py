"""
Regression test for EoS adapter session_id fix.

This test verifies that BackendCompletionFlow correctly generates and synchronizes
session identifiers even when the client does not provide one, ensuring that
the EoS adapter always receives a non-empty session_id.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import BackendError
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import ProcessingContext, RequestContext
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


@pytest.fixture
def mock_dependencies():
    """Create mock dependencies for BackendCompletionFlow."""
    return {
        "availability_checker": MagicMock(),
        "request_preparer": MagicMock(),
        "session_resolver": MagicMock(),
        "backend_invoker": MagicMock(),
        "failover_executor": MagicMock(),
        "wire_capture_orchestrator": MagicMock(),
        "usage_accounting_orchestrator": MagicMock(),
        "stream_formatting_service": MagicMock(),
        "eos_adapter": MagicMock(),
        "resilience_coordinator": MagicMock(),
        "exception_normalizer": MagicMock(),
        "connector_invoker": MagicMock(),
    }

@pytest.mark.asyncio
async def test_call_completion_generates_and_syncs_session_id_on_error(mock_dependencies):
    """
    Test that session_id is generated and synchronized back to context on error.
    
    This covers the fix for the "Missing session_id" log in EoS adapter.
    """
    # 1. Setup mocks
    mock_dependencies["exception_normalizer"].normalize = MagicMock(side_effect=lambda e, b: e)
    mock_dependencies["request_preparer"].prepare_request = AsyncMock(
        return_value=MagicMock(backend="openai", model="gpt-4", uri_params={})
    )
    mock_dependencies["request_preparer"].synchronize_request_with_target = MagicMock(
        side_effect=lambda r, t: r
    )
    mock_dependencies["request_preparer"].prepare_backend_request = AsyncMock(
        side_effect=lambda r, b, s, u: r
    )
    
    # Return (None, None) to simulate missing session
    mock_dependencies["session_resolver"].resolve_session = AsyncMock(
        return_value=(None, None)
    )
    
    # Mock backend to fail
    mock_backend = MagicMock()
    mock_backend.invoke = AsyncMock(side_effect=BackendError("Backend failure", "openai"))
    mock_dependencies["backend_invoker"].acquire_backend = AsyncMock(return_value=mock_backend)
    
    mock_dependencies["availability_checker"].check_backend_availability = AsyncMock()
    mock_dependencies["failover_executor"].check_complex_failover = AsyncMock(return_value=False)
    mock_dependencies["failover_executor"].apply_failure_recovery = AsyncMock(
        side_effect=lambda **kwargs: kwargs["error"]
    )
    
    # EoS adapter mock
    mock_eos_adapter = MagicMock()
    mock_eos_adapter.record_error_termination = AsyncMock()
    mock_dependencies["eos_adapter"] = mock_eos_adapter

    # 2. Create flow and context
    flow = BackendCompletionFlow(**mock_dependencies)
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        session_id=None, # Missing session_id
        processing_context=ProcessingContext(),
    )
    
    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="test")]
    )

    # 3. Execute - should raise BackendError
    with pytest.raises(BackendError):
        await flow.call_completion(request=request, context=context, allow_failover=False)

    # 4. Verify EoS adapter was called with a generated session_id
    assert mock_eos_adapter.record_error_termination.called
    call_args = mock_eos_adapter.record_error_termination.call_args
    session_id_passed = call_args.kwargs["session_id"]
    
    assert session_id_passed is not None
    assert len(session_id_passed) > 0
    
    # 5. Verify context.session_id was synchronized
    assert context.session_id == session_id_passed
    
    # 6. Verify backend acquisition used the same session_id
    mock_dependencies["backend_invoker"].acquire_backend.assert_called_with("openai", session_id_passed)

@pytest.mark.asyncio
async def test_call_completion_preserves_existing_session_id_on_error(mock_dependencies):
    """
    Test that existing session_id is preserved and passed to EoS adapter.
    """
    # 1. Setup mocks
    mock_dependencies["exception_normalizer"].normalize = MagicMock(side_effect=lambda e, b: e)
    mock_dependencies["request_preparer"].prepare_request = AsyncMock(
        return_value=MagicMock(backend="openai", model="gpt-4", uri_params={})
    )
    mock_dependencies["request_preparer"].synchronize_request_with_target = MagicMock(
        side_effect=lambda r, t: r
    )
    mock_dependencies["request_preparer"].prepare_backend_request = AsyncMock(
        side_effect=lambda r, b, s, u: r
    )
    
    existing_session_id = "existing-session-123"
    mock_dependencies["session_resolver"].resolve_session = AsyncMock(
        return_value=(MagicMock(), existing_session_id)
    )
    
    # Mock backend to fail
    mock_backend = MagicMock()
    mock_backend.invoke = AsyncMock(side_effect=BackendError("Backend failure", "openai"))
    mock_dependencies["backend_invoker"].acquire_backend = AsyncMock(return_value=mock_backend)
    
    mock_dependencies["availability_checker"].check_backend_availability = AsyncMock()
    mock_dependencies["failover_executor"].check_complex_failover = AsyncMock(return_value=False)
    
    # EoS adapter mock
    mock_eos_adapter = MagicMock()
    mock_eos_adapter.record_error_termination = AsyncMock()
    mock_dependencies["eos_adapter"] = mock_eos_adapter

    # 2. Create flow and context
    flow = BackendCompletionFlow(**mock_dependencies)
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        session_id=existing_session_id,
        processing_context=ProcessingContext(),
    )
    
    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="test")]
    )

    # 3. Execute - should raise BackendError
    with pytest.raises(BackendError):
        await flow.call_completion(request=request, context=context, allow_failover=False)

    # 4. Verify EoS adapter was called with the existing session_id
    assert mock_eos_adapter.record_error_termination.called
    call_args = mock_eos_adapter.record_error_termination.call_args
    assert call_args.kwargs["session_id"] == existing_session_id
    
    # 5. Verify context.session_id remains correct
    assert context.session_id == existing_session_id
