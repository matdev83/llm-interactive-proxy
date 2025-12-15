"""
Unit tests for BackendPreparer component.

These tests cover backend request preparation and validation logic
extracted from RequestProcessor during refactoring.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import InvalidRequestError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_request_manager_interface import IBackendRequestManager
from src.core.services.backend_preparer import BackendPreparer


@pytest.fixture
def mock_backend_request_manager() -> IBackendRequestManager:
    """Create a mock backend request manager."""
    mock = AsyncMock(spec=IBackendRequestManager)

    async def prepare_backend_request(request, processed_result):
        return request

    mock.prepare_backend_request.side_effect = prepare_backend_request
    return mock


@pytest.fixture
def mock_app_state() -> IApplicationState:
    """Create a mock application state."""
    mock = MagicMock(spec=IApplicationState)
    mock.get_model_defaults.return_value = {}
    mock.get_backend_type.return_value = "openai"
    mock.get_setting.return_value = None
    return mock


@pytest.fixture
def request_context(mock_app_state) -> RequestContext:
    """Create a minimal request context."""
    return RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=mock_app_state,
        client_host="127.0.0.1",
        original_request=None,
    )


@pytest.fixture
def backend_preparer(mock_backend_request_manager, mock_app_state) -> BackendPreparer:
    """Create a BackendPreparer instance with mocked dependencies."""
    return BackendPreparer(
        backend_request_manager=mock_backend_request_manager, app_state=mock_app_state
    )


@pytest.mark.asyncio
async def test_prepare_successful_backend_request(
    backend_preparer, request_context, mock_backend_request_manager
):
    """When backend preparation succeeds, should return prepared request."""
    # Arrange
    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="Hello")]
    )
    processed = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="Hello")],
        command_executed=False,
        command_results=[],
    )

    # Act
    result = await backend_preparer.prepare(
        request_context, session_id, request, processed
    )

    # Assert
    assert result is not None
    assert result.model == "gpt-4"
    mock_backend_request_manager.prepare_backend_request.assert_called_once_with(
        request, processed
    )


@pytest.mark.asyncio
async def test_prepare_can_return_none_to_skip_backend(request_context, mock_app_state):
    """When backend request manager returns None, should pass through."""
    # Arrange
    # Create a fresh mock that returns None
    mock_brm = AsyncMock(spec=IBackendRequestManager)
    mock_brm.prepare_backend_request.return_value = None

    preparer = BackendPreparer(
        backend_request_manager=mock_brm, app_state=mock_app_state
    )

    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="Hello")]
    )
    processed = ProcessedResult(
        modified_messages=[], command_executed=False, command_results=[]
    )

    # Act
    result = await preparer.prepare(request_context, session_id, request, processed)

    # Assert
    assert result is None


@pytest.mark.asyncio
async def test_prepare_input_token_limit_exceeded_raises_error(
    backend_preparer, request_context, mock_app_state
):
    """When input tokens exceed limit, should raise InvalidRequestError."""
    # Arrange
    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="x" * 10000)],  # Large message
    )
    processed = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="x" * 10000)],
        command_executed=False,
        command_results=[],
    )

    # Configure model with token limit
    mock_app_state.get_model_defaults.return_value = {
        "gpt-4": {"limits": {"max_input_tokens": 100}}
    }

    # Act & Assert
    with pytest.raises(InvalidRequestError) as exc_info:
        await backend_preparer.prepare(request_context, session_id, request, processed)

    assert exc_info.value.code == "input_limit_exceeded"
    assert exc_info.value.param == "messages"


@pytest.mark.asyncio
async def test_prepare_total_token_limit_exceeded_raises_error(
    backend_preparer, request_context, mock_app_state, mock_backend_request_manager
):
    """When total tokens (input + max_tokens) exceed context window, should raise InvalidRequestError."""
    # Arrange
    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="Hello")],
        max_tokens=500,
    )
    processed = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="Hello")],
        command_executed=False,
        command_results=[],
    )

    # Prepare backend request with max_tokens
    async def prepare_with_max_tokens(req, proc):
        return req.model_copy(update={"max_tokens": 500})

    mock_backend_request_manager.prepare_backend_request.side_effect = (
        prepare_with_max_tokens
    )

    # Configure model with small context window
    mock_app_state.get_model_defaults.return_value = {
        "gpt-4": {"limits": {"context_window": 200, "max_input_tokens": 200}}
    }

    # Act & Assert
    with pytest.raises(InvalidRequestError) as exc_info:
        await backend_preparer.prepare(request_context, session_id, request, processed)

    assert exc_info.value.code == "total_limit_exceeded"
    assert exc_info.value.param == "max_tokens"


@pytest.mark.asyncio
async def test_prepare_cli_context_window_override_applied(
    backend_preparer, request_context, mock_app_state
):
    """When CLI context window override is set, should use it instead of model defaults."""
    # Arrange
    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="x" * 5000)],  # Medium message
    )
    processed = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="x" * 5000)],
        command_executed=False,
        command_results=[],
    )

    # Configure model with small limit
    mock_app_state.get_model_defaults.return_value = {
        "gpt-4": {"limits": {"max_input_tokens": 100}}
    }

    # Configure CLI override with large limit
    mock_config = MagicMock()
    mock_config.context_window_override = 100000
    mock_app_state.get_setting.return_value = mock_config

    # Act - should NOT raise because CLI override is larger
    result = await backend_preparer.prepare(
        request_context, session_id, request, processed
    )

    # Assert
    assert result is not None  # Should succeed with override


@pytest.mark.asyncio
async def test_prepare_unexpected_error_fails_open(
    backend_preparer, request_context, mock_app_state
):
    """When unexpected error occurs during validation, should fail-open and continue."""
    # Arrange
    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="Hello")]
    )
    processed = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="Hello")],
        command_executed=False,
        command_results=[],
    )

    # Configure app_state to raise unexpected error during token counting
    def raise_error():
        raise RuntimeError("Unexpected token counting error")

    mock_app_state.get_model_defaults.side_effect = raise_error

    # Act - should NOT raise, should fail-open
    result = await backend_preparer.prepare(
        request_context, session_id, request, processed
    )

    # Assert
    assert result is not None  # Should continue despite error


@pytest.mark.asyncio
async def test_prepare_without_app_state_skips_validation(backend_preparer_no_state):
    """When app_state is None, should skip validation and return request."""
    # Arrange
    mock_brm = AsyncMock(spec=IBackendRequestManager)

    async def prepare_backend_request(request, processed_result):
        return request

    mock_brm.prepare_backend_request.side_effect = prepare_backend_request

    preparer = BackendPreparer(backend_request_manager=mock_brm, app_state=None)

    context = RequestContext(
        headers={},
        cookies={},
        state=MagicMock(),
        app_state=MagicMock(),
        client_host="127.0.0.1",
        original_request=None,
    )
    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="Hello")]
    )
    processed = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="Hello")],
        command_executed=False,
        command_results=[],
    )

    # Act
    result = await preparer.prepare(context, session_id, request, processed)

    # Assert
    assert result is not None
    assert result.model == "gpt-4"


@pytest.fixture
def backend_preparer_no_state(mock_backend_request_manager) -> BackendPreparer:
    """Create a BackendPreparer without app_state."""
    return BackendPreparer(
        backend_request_manager=mock_backend_request_manager, app_state=None
    )
