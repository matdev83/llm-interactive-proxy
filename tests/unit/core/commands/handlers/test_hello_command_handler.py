"""
Unit tests for the HelloCommandHandler.
"""

from unittest.mock import MagicMock

import pytest
from src.core.commands.command import Command
from src.core.commands.handlers.hello_command_handler import HelloCommandHandler
from src.core.domain.session import Session, SessionState


@pytest.mark.asyncio
async def test_hello_command_handler():
    """
    Tests that the HelloCommandHandler returns a welcome message and updates the
    session state.
    """
    # Arrange
    mock_command_service = MagicMock()
    handler = HelloCommandHandler(mock_command_service)
    command = Command(name="hello")
    session_state = SessionState()
    session = Session(session_id="test_session", state=session_state)

    # Act
    result = await handler.handle(command, session)

    # Assert
    assert result.success
    assert "Welcome to LLM Interactive Proxy!" in result.message
    assert result.new_state is not None
    assert result.new_state.hello_requested
