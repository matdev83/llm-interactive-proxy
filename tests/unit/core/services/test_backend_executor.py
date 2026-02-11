"""
Unit tests for BackendExecutor.

Tests backend execution and persistence side effects following TDD principles.
"""

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.services.backend_executor import BackendExecutor


@pytest.fixture
def mock_backend_request_manager():
    """Create a mock backend request manager."""
    manager = AsyncMock()
    manager.process_backend_request = AsyncMock()
    return manager


@pytest.fixture
def mock_session_manager():
    """Create a mock session manager."""
    manager = AsyncMock()
    manager.update_session_history = AsyncMock()
    manager.update_session_fingerprint = AsyncMock()
    return manager


@pytest.fixture
def mock_replacement_service():
    """Create a mock replacement service."""
    service = Mock()
    service.complete_turn = Mock()
    return service


@pytest.fixture
def backend_executor(
    mock_backend_request_manager, mock_session_manager, mock_replacement_service
):
    """Create a BackendExecutor instance with mocked dependencies."""
    return BackendExecutor(
        backend_request_manager=mock_backend_request_manager,
        session_manager=mock_session_manager,
        replacement_service=mock_replacement_service,
    )


@pytest.fixture
def sample_request():
    """Create a sample ChatRequest."""
    return ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
    )


@pytest.fixture
def sample_context():
    """Create a sample RequestContext."""
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=MagicMock(),
    )


@pytest.fixture
def sample_session():
    """Create a sample session object."""
    session = Mock()
    session.agent = "test-agent"
    return session


@pytest.fixture
def sample_response():
    """Create a sample backend response."""
    return ResponseEnvelope(
        content={"content": "Hello there!"},
        headers={},
        usage=None,
    )


@pytest.mark.asyncio
async def test_happy_path_backend_execution(
    backend_executor,
    mock_backend_request_manager,
    mock_session_manager,
    mock_replacement_service,
    sample_context,
    sample_session,
    sample_request,
    sample_response,
):
    """Test successful backend execution with all side effects."""
    # Arrange
    session_id = "test-session-123"
    mock_backend_request_manager.process_backend_request.return_value = sample_response

    # Act
    result = await backend_executor.execute(
        context=sample_context,
        session=sample_session,
        session_id=session_id,
        request=sample_request,
        original_request=sample_request,
    )

    # Assert
    assert result == sample_response
    mock_backend_request_manager.process_backend_request.assert_called_once()
    # History should be called with original_request, backend_request (with session_id injected), response
    call_args = mock_session_manager.update_session_history.call_args[0]
    assert call_args[0] == sample_request  # original_request
    assert (
        call_args[1].session_id == session_id
    )  # backend_request should have session_id
    assert call_args[2] == sample_response  # response
    assert call_args[3] == session_id  # session_id parameter
    mock_session_manager.update_session_fingerprint.assert_called_once()
    mock_replacement_service.complete_turn.assert_called_once_with(session_id)


@pytest.mark.asyncio
async def test_session_id_injection_when_absent(
    backend_executor,
    mock_backend_request_manager,
    sample_context,
    sample_session,
    sample_request,
    sample_response,
):
    """Test that session_id is injected into extra_body when absent."""
    # Arrange
    session_id = "test-session-456"
    mock_backend_request_manager.process_backend_request.return_value = sample_response

    # Act
    await backend_executor.execute(
        context=sample_context,
        session=sample_session,
        session_id=session_id,
        request=sample_request,
        original_request=sample_request,
    )

    # Assert
    call_args = mock_backend_request_manager.process_backend_request.call_args
    injected_request = call_args[0][0]
    assert injected_request.extra_body["session_id"] == session_id
    assert injected_request.session_id == session_id


@pytest.mark.asyncio
async def test_session_id_preservation_when_present(
    backend_executor,
    mock_backend_request_manager,
    sample_context,
    sample_session,
    sample_response,
):
    """Test that existing session_id in extra_body is preserved."""
    # Arrange
    session_id = "test-session-789"
    existing_session_id = "existing-session-999"
    request_with_session = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        extra_body={"session_id": existing_session_id, "other_field": "value"},
    )
    mock_backend_request_manager.process_backend_request.return_value = sample_response

    # Act
    await backend_executor.execute(
        context=sample_context,
        session=sample_session,
        session_id=session_id,
        request=request_with_session,
        original_request=request_with_session,
    )

    # Assert
    call_args = mock_backend_request_manager.process_backend_request.call_args
    injected_request = call_args[0][0]
    # Should preserve the existing session_id
    assert injected_request.extra_body["session_id"] == existing_session_id
    # Should still set the session_id field
    assert injected_request.session_id == session_id
    # Should preserve other fields
    assert injected_request.extra_body["other_field"] == "value"


@pytest.mark.asyncio
async def test_history_update_uses_correct_requests(
    backend_executor,
    mock_backend_request_manager,
    mock_session_manager,
    sample_context,
    sample_session,
    sample_response,
):
    """Test that session history is updated with original_request and backend_request."""
    # Arrange
    session_id = "test-session-abc"
    original_request = ChatRequest(
        model="gpt-3.5-turbo",
        messages=[ChatMessage(role="user", content="Original")],
    )
    backend_request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Transformed")],
    )
    mock_backend_request_manager.process_backend_request.return_value = sample_response

    # Act
    await backend_executor.execute(
        context=sample_context,
        session=sample_session,
        session_id=session_id,
        request=backend_request,
        original_request=original_request,
    )

    # Assert
    # History should receive original_request, transformed backend_request, and response
    call_args = mock_session_manager.update_session_history.call_args[0]
    assert call_args[0] == original_request  # First arg should be original
    # Second arg should be the transformed backend request (with session_id injected)
    assert call_args[1].model == "gpt-4"
    assert call_args[2] == sample_response
    assert call_args[3] == session_id


@pytest.mark.asyncio
async def test_auxiliary_request_uses_derived_session_id_and_skips_side_effects(
    backend_executor,
    mock_backend_request_manager,
    mock_session_manager,
    mock_replacement_service,
    sample_context,
    sample_session,
    sample_request,
    sample_response,
):
    """Auxiliary requests should not affect primary session lifecycle."""

    session_id = "primary-session-1"
    aux_session_id = f"aux::{session_id}"
    sample_context.extensions["auxiliary_request"] = True
    sample_context.extensions["auxiliary_effective_session_id"] = aux_session_id

    mock_backend_request_manager.process_backend_request.return_value = sample_response

    await backend_executor.execute(
        context=sample_context,
        session=sample_session,
        session_id=session_id,
        request=sample_request,
        original_request=sample_request,
    )

    call_args = mock_backend_request_manager.process_backend_request.call_args[0]
    injected_request = call_args[0]
    assert injected_request.session_id == aux_session_id
    assert injected_request.extra_body["session_id"] == aux_session_id
    assert call_args[1] == aux_session_id

    mock_session_manager.update_session_history.assert_not_called()
    mock_session_manager.update_session_fingerprint.assert_not_called()
    mock_replacement_service.complete_turn.assert_not_called()


@pytest.mark.asyncio
async def test_fingerprint_update_fail_open(
    backend_executor,
    mock_backend_request_manager,
    mock_session_manager,
    sample_context,
    sample_session,
    sample_request,
    sample_response,
):
    """Test that fingerprint update failures don't block execution."""
    # Arrange
    session_id = "test-session-def"
    mock_backend_request_manager.process_backend_request.return_value = sample_response
    mock_session_manager.update_session_fingerprint.side_effect = Exception(
        "Fingerprint failure"
    )

    # Act - should not raise
    result = await backend_executor.execute(
        context=sample_context,
        session=sample_session,
        session_id=session_id,
        request=sample_request,
        original_request=sample_request,
    )

    # Assert
    assert result == sample_response  # Should still return response
    mock_session_manager.update_session_fingerprint.assert_called_once()


@pytest.mark.asyncio
async def test_backend_error_propagates_unchanged(
    backend_executor,
    mock_backend_request_manager,
    mock_replacement_service,
    sample_context,
    sample_session,
    sample_request,
):
    """Test that backend errors propagate without wrapping."""
    # Arrange
    session_id = "test-session-ghi"
    backend_error = RuntimeError("Backend service unavailable")
    mock_backend_request_manager.process_backend_request.side_effect = backend_error

    # Act & Assert
    with pytest.raises(RuntimeError, match="Backend service unavailable"):
        await backend_executor.execute(
            context=sample_context,
            session=sample_session,
            session_id=session_id,
            request=sample_request,
            original_request=sample_request,
        )

    # Turn completion should still run in finally block
    mock_replacement_service.complete_turn.assert_called_once_with(session_id)


@pytest.mark.asyncio
async def test_turn_completion_on_success(
    backend_executor,
    mock_backend_request_manager,
    mock_replacement_service,
    sample_context,
    sample_session,
    sample_request,
    sample_response,
):
    """Test that turn completion is called after successful execution."""
    # Arrange
    session_id = "test-session-jkl"
    mock_backend_request_manager.process_backend_request.return_value = sample_response

    # Act
    await backend_executor.execute(
        context=sample_context,
        session=sample_session,
        session_id=session_id,
        request=sample_request,
        original_request=sample_request,
    )

    # Assert
    mock_replacement_service.complete_turn.assert_called_once_with(session_id)


@pytest.mark.asyncio
async def test_turn_completion_on_error(
    backend_executor,
    mock_backend_request_manager,
    mock_replacement_service,
    sample_context,
    sample_session,
    sample_request,
):
    """Test that turn completion is called even when backend raises."""
    # Arrange
    session_id = "test-session-mno"
    mock_backend_request_manager.process_backend_request.side_effect = RuntimeError(
        "Test error"
    )

    # Act & Assert
    with pytest.raises(RuntimeError):
        await backend_executor.execute(
            context=sample_context,
            session=sample_session,
            session_id=session_id,
            request=sample_request,
            original_request=sample_request,
        )

    # Turn completion should still run
    mock_replacement_service.complete_turn.assert_called_once_with(session_id)


@pytest.mark.asyncio
async def test_turn_completion_uses_effective_replacement_session_id_from_context(
    backend_executor,
    mock_backend_request_manager,
    mock_replacement_service,
    sample_context,
    sample_session,
    sample_request,
    sample_response,
):
    """Turn completion should honor replacement continuity key when provided."""
    session_id = "llm-b2bua-ephemeral"
    replacement_session_id = "b2bua-scope:user-123:abcdef1234567890"
    sample_context.extensions["replacement_effective_session_id"] = (
        replacement_session_id
    )
    mock_backend_request_manager.process_backend_request.return_value = sample_response

    await backend_executor.execute(
        context=sample_context,
        session=sample_session,
        session_id=session_id,
        request=sample_request,
        original_request=sample_request,
    )

    mock_replacement_service.complete_turn.assert_called_once_with(
        replacement_session_id
    )


@pytest.mark.asyncio
async def test_no_replacement_service_does_not_crash(
    mock_backend_request_manager,
    mock_session_manager,
    sample_context,
    sample_session,
    sample_request,
    sample_response,
):
    """Test that executor works when replacement_service is None."""
    # Arrange
    executor_no_replacement = BackendExecutor(
        backend_request_manager=mock_backend_request_manager,
        session_manager=mock_session_manager,
        replacement_service=None,  # No replacement service
    )
    session_id = "test-session-pqr"
    mock_backend_request_manager.process_backend_request.return_value = sample_response

    # Act - should not crash
    result = await executor_no_replacement.execute(
        context=sample_context,
        session=sample_session,
        session_id=session_id,
        request=sample_request,
        original_request=sample_request,
    )

    # Assert
    assert result == sample_response


@pytest.mark.asyncio
async def test_fingerprint_method_missing_does_not_crash(
    mock_backend_request_manager,
    sample_context,
    sample_session,
    sample_request,
    sample_response,
):
    """Test that executor works when session_manager lacks update_session_fingerprint."""
    # Arrange
    session_manager_no_fingerprint = AsyncMock()
    session_manager_no_fingerprint.update_session_history = AsyncMock()
    # No update_session_fingerprint method

    executor = BackendExecutor(
        backend_request_manager=mock_backend_request_manager,
        session_manager=session_manager_no_fingerprint,
        replacement_service=None,
    )
    session_id = "test-session-stu"
    mock_backend_request_manager.process_backend_request.return_value = sample_response

    # Act - should not crash
    result = await executor.execute(
        context=sample_context,
        session=sample_session,
        session_id=session_id,
        request=sample_request,
        original_request=sample_request,
    )

    # Assert
    assert result == sample_response
    session_manager_no_fingerprint.update_session_history.assert_called_once()
