"""
Unit tests for the HelpCommandHandler.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.commands.command import Command
from src.core.commands.handlers.hello_command_handler import HelloCommandHandler
from src.core.commands.handlers.help_command_handler import HelpCommandHandler
from src.core.domain.session import Session, SessionState
from src.core.interfaces.command_service_interface import ICommandService


@pytest.fixture
def mock_command_service() -> MagicMock:
    """Fixture for a mock command service."""
    service = MagicMock(spec=ICommandService)
    # Mock methods that HelpCommandHandler might call on ICommandService
    service.get_all_commands = AsyncMock(
        return_value={
            "hello": HelloCommandHandler(service),
            "help": HelpCommandHandler(service),
        }
    )
    service.get_command_handler = AsyncMock(return_value=HelloCommandHandler)
    return service


@pytest.mark.asyncio
async def test_help_command_handler_no_args(mock_command_service: MagicMock):
    """
    Tests that the HelpCommandHandler returns a list of all commands when no
    arguments are provided.
    """
    # Arrange
    handler = HelpCommandHandler(mock_command_service)
    command = Command(name="help")
    session_state = SessionState()
    session = Session(session_id="test_session", state=session_state)

    # Act
    result = await handler.handle(command, session)

    # Assert
    assert result.success
    assert "Available commands:" in result.message
    assert "hello - Greets the user." in result.message
    mock_command_service.get_all_commands.assert_called_once()


@pytest.mark.asyncio
async def test_help_command_handler_with_arg(mock_command_service: MagicMock):
    """
    Tests that the HelpCommandHandler returns help for a specific command
    when an argument is provided.
    """
    # Arrange
    handler = HelpCommandHandler(mock_command_service)
    command = Command(name="help", args={"command_name": "hello"})
    session_state = SessionState()
    session = Session(session_id="test_session", state=session_state)

    # Act
    result = await handler.handle(command, session)

    # Assert
    assert result.success
    assert "hello - Greets the user." in result.message
    assert "Format: hello" in result.message
    assert "Examples:" in result.message
    assert "hello" in result.message
    mock_command_service.get_command_handler.assert_called_once_with("hello")
