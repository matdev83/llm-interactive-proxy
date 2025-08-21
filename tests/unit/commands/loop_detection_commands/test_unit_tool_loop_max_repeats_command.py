from unittest.mock import Mock

import pytest
from src.core.domain.commands.loop_detection_commands.tool_loop_max_repeats_command import (
    ToolLoopMaxRepeatsCommand,
)
from src.core.domain.session import LoopDetectionConfiguration, Session, SessionState


@pytest.fixture
def command() -> ToolLoopMaxRepeatsCommand:
    return ToolLoopMaxRepeatsCommand()


@pytest.fixture
def mock_session() -> Mock:
    mock = Mock(spec=Session)
    mock.state = SessionState(loop_config=LoopDetectionConfiguration())
    return mock


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Loop detection is disabled due to legacy/invalid implementation. TODO: Implement gemini-cli inspired fast hash-based loop detection."
)
async def test_max_repeats_success(
    command: ToolLoopMaxRepeatsCommand, mock_session: Mock
):
    # Arrange
    args = {"max_repeats": "5"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "Tool loop max repeats set to 5"
    assert result.new_state.loop_config.tool_loop_max_repeats == 5


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Loop detection is disabled due to legacy/invalid implementation. TODO: Implement gemini-cli inspired fast hash-based loop detection."
)
async def test_max_repeats_failure_invalid_int(
    command: ToolLoopMaxRepeatsCommand, mock_session: Mock
):
    # Arrange
    args = {"max_repeats": "abc"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert result.message == "Max repeats must be a valid integer"


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Loop detection is disabled due to legacy/invalid implementation. TODO: Implement gemini-cli inspired fast hash-based loop detection."
)
async def test_max_repeats_failure_too_low(
    command: ToolLoopMaxRepeatsCommand, mock_session: Mock
):
    # Arrange
    args = {"max_repeats": "1"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert result.message == "Max repeats must be at least 2"


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Loop detection is disabled due to legacy/invalid implementation. TODO: Implement gemini-cli inspired fast hash-based loop detection."
)
async def test_max_repeats_failure_no_value(
    command: ToolLoopMaxRepeatsCommand, mock_session: Mock
):
    # Arrange
    args = {"max_repeats": None}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert result.message == "Max repeats must be specified"
