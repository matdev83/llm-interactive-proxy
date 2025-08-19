
import pytest
from unittest.mock import Mock
import asyncio

from src.core.domain.commands.loop_detection_commands.tool_loop_mode_command import ToolLoopModeCommand
from src.core.domain.session import Session, SessionState, LoopDetectionConfiguration
from src.tool_call_loop.config import ToolLoopMode

@pytest.fixture
def command() -> ToolLoopModeCommand:
    return ToolLoopModeCommand()

@pytest.fixture
def mock_session() -> Mock:
    mock = Mock(spec=Session)
    mock.state = SessionState(loop_config=LoopDetectionConfiguration())
    return mock

@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["break", "chance_then_break"])
async def test_tool_loop_mode_success(command: ToolLoopModeCommand, mock_session: Mock, mode: str):
    # Arrange
    args = {"mode": mode}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == f"Tool loop mode set to {mode}"
    assert result.new_state.loop_config.tool_loop_mode == ToolLoopMode(mode)

@pytest.mark.asyncio
async def test_tool_loop_mode_failure_invalid(command: ToolLoopModeCommand, mock_session: Mock):
    # Arrange
    args = {"mode": "invalid"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert "Invalid mode 'invalid'" in result.message

@pytest.mark.asyncio
async def test_tool_loop_mode_failure_no_mode(command: ToolLoopModeCommand, mock_session: Mock):
    # Arrange
    args = {"mode": None}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert result.message == "Mode must be specified"
