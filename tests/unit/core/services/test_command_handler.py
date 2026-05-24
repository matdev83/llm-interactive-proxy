"""
Unit tests for CommandHandler component.

These tests cover the command processing and command-only flow logic
extracted from RequestProcessor during refactoring.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ProcessedResponse, ResponseEnvelope
from src.core.domain.session import Session
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.response_manager_interface import IResponseManager
from src.core.interfaces.session_manager_interface import ISessionManager
from src.core.services.artifact_service import ArtifactService
from src.core.services.command_handler import CommandHandler


@pytest.fixture
def mock_command_processor() -> ICommandProcessor:
    """Create a mock command processor."""
    mock = AsyncMock(spec=ICommandProcessor)
    # Default: no commands executed
    mock.process_messages.return_value = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="Hello")],
        command_executed=False,
        command_results=[],
    )
    return mock


@pytest.fixture
def mock_session_manager() -> ISessionManager:
    """Create a mock session manager."""
    mock = AsyncMock(spec=ISessionManager)
    mock.record_command_in_session.return_value = None
    return mock


@pytest.fixture
def mock_response_manager() -> IResponseManager:
    """Create a mock response manager."""
    mock = AsyncMock(spec=IResponseManager)
    response = ResponseEnvelope(
        content=ProcessedResponse(
            content="command response",
            usage={"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
        ),
        status_code=200,
    )
    mock.process_command_result.return_value = response
    return mock


@pytest.fixture
def mock_app_state() -> IApplicationState:
    """Create a mock application state."""
    mock = MagicMock(spec=IApplicationState)
    mock.get_disable_commands.return_value = False
    mock.get_disable_interactive_commands.return_value = False
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
def mock_artifact_service() -> ArtifactService:
    """Create a mock artifact service."""
    return MagicMock(spec=ArtifactService)


@pytest.fixture
def command_handler(
    mock_command_processor,
    mock_session_manager,
    mock_response_manager,
    mock_app_state,
    mock_artifact_service,
) -> CommandHandler:
    """Create a CommandHandler instance with mocked dependencies."""
    return CommandHandler(
        command_processor=mock_command_processor,
        session_manager=mock_session_manager,
        response_manager=mock_response_manager,
        app_state=mock_app_state,
        artifact_service=mock_artifact_service,
    )


@pytest.mark.asyncio
async def test_handle_when_commands_disabled_returns_processed_result(
    command_handler, mock_app_state, mock_command_processor, request_context
):
    """When global commands are disabled, handler should skip command processing."""
    # Arrange
    mock_app_state.get_disable_commands.return_value = True
    context = request_context
    session = MagicMock(spec=Session)
    session.agent = "test-agent"
    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="!/help")]
    )

    # Act
    result = await command_handler.handle(context, session, session_id, request)

    # Assert
    assert isinstance(result, ProcessedResult)
    assert result.command_executed is False
    # When commands are disabled, commands are filtered from messages for security
    assert len(result.modified_messages) == 1
    assert (
        result.modified_messages[0].content == ""
    )  # Command "!/help" was filtered out
    mock_command_processor.process_messages.assert_not_called()


@pytest.mark.asyncio
async def test_handle_when_no_commands_executed_returns_processed_result(
    command_handler, mock_command_processor, request_context
):
    """When no commands are executed, handler should return backend flow."""
    # Arrange
    context = request_context
    session = MagicMock(spec=Session)
    session.agent = "test-agent"
    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="Hello")]
    )

    processed = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="Hello")],
        command_executed=False,
        command_results=[],
    )
    mock_command_processor.process_messages.return_value = processed

    # Act
    result = await command_handler.handle(context, session, session_id, request)

    # Assert
    assert isinstance(result, ProcessedResult)
    assert result == processed


@pytest.mark.asyncio
async def test_handle_command_only_path_returns_response_envelope(
    command_handler,
    mock_command_processor,
    mock_session_manager,
    mock_response_manager,
    mock_artifact_service,
    request_context,
):
    """When command-only path is taken, handler should return response envelope."""
    # Arrange
    context = request_context
    session = MagicMock(spec=Session)
    session.agent = "test-agent"
    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="!/help")]
    )

    # Command executed but no modified messages -> command-only path
    processed = ProcessedResult(
        modified_messages=[],  # Empty list, not None
        command_executed=True,
        command_results=["command output"],
    )
    mock_command_processor.process_messages.return_value = processed

    # Act
    result = await command_handler.handle(context, session, session_id, request)

    # Assert
    assert isinstance(result, ResponseEnvelope)
    mock_artifact_service.normalize_artifact_previews.assert_called_once_with(processed)
    mock_session_manager.record_command_in_session.assert_called_once_with(
        request, session_id
    )
    mock_response_manager.process_command_result.assert_called_once_with(
        processed, session
    )


@pytest.mark.asyncio
async def test_handle_cline_agent_fast_path(
    command_handler,
    mock_command_processor,
    mock_session_manager,
    mock_response_manager,
    mock_artifact_service,
    request_context,
):
    """When Cline agent has executed command, take fast-path."""
    # Arrange
    context = request_context
    session = MagicMock(spec=Session)
    session.agent = "cline"
    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="!/help")]
    )

    processed = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="!/help")],
        command_executed=True,
        command_results=["command output"],
    )
    mock_command_processor.process_messages.return_value = processed

    # Act
    result = await command_handler.handle(context, session, session_id, request)

    # Assert
    assert isinstance(result, ResponseEnvelope)
    mock_artifact_service.normalize_artifact_previews.assert_called_once()
    mock_session_manager.record_command_in_session.assert_called_once()
    mock_response_manager.process_command_result.assert_called_once()


@pytest.mark.asyncio
async def test_handle_cline_agent_fast_path_fallback_on_attribute_error(
    command_handler,
    mock_command_processor,
    mock_session_manager,
    mock_response_manager,
    mock_artifact_service,
    request_context,
):
    """When Cline agent fast-path fails, continue to normal processing."""
    # Arrange
    context = request_context
    session = MagicMock(spec=Session)
    session.agent = None  # This will cause AttributeError in fast-path
    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="Hello")]
    )

    processed = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="Hello")],
        command_executed=True,  # Command executed
        command_results=["output"],
    )
    mock_command_processor.process_messages.return_value = processed

    # Act
    result = await command_handler.handle(context, session, session_id, request)

    # Assert
    # Should continue to normal backend flow, not command-only
    assert isinstance(result, ProcessedResult)


@pytest.mark.asyncio
async def test_handle_artifact_normalization_always_runs_after_commands(
    command_handler, mock_command_processor, mock_artifact_service, request_context
):
    """Artifact normalization should run after command processing."""
    # Arrange
    context = request_context
    session = MagicMock(spec=Session)
    session.agent = "test-agent"
    session_id = "test-session"
    request = ChatRequest(
        model="gpt-4", messages=[ChatMessage(role="user", content="!/help")]
    )

    processed = ProcessedResult(
        modified_messages=[ChatMessage(role="user", content="Hello")],
        command_executed=True,
        command_results=[],
    )
    mock_command_processor.process_messages.return_value = processed

    # Act
    await command_handler.handle(context, session, session_id, request)

    # Assert
    mock_artifact_service.normalize_artifact_previews.assert_called_once_with(processed)
