import pytest
from unittest.mock import Mock
import asyncio

from src.core.domain.commands.hello_command import HelloCommand
from src.core.domain.session import Session, SessionState

@pytest.fixture
def command() -> HelloCommand:
    """Returns a new instance of the HelloCommand for each test."""
    return HelloCommand()

@pytest.fixture
def mock_session() -> Mock:
    """Creates a mock session object with a default state."""
    mock = Mock(spec=Session)
    mock.state = SessionState()
    return mock

@pytest.mark.asyncio
async def test_hello_command_execution(command: HelloCommand, mock_session: Mock):
    """Test that the HelloCommand executes correctly."""
    # Arrange
    args = {}
    context = {}

    # Act
    result = await command.execute(args, mock_session, context)

    # Assert
    assert result.success is True
    assert "Welcome to LLM Interactive Proxy!" in result.message
    assert result.new_state is not None
    assert result.new_state.hello_requested is True