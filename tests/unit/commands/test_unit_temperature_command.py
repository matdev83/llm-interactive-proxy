
from unittest.mock import Mock

import pytest
from src.core.domain.commands.temperature_command import TemperatureCommand
from src.core.domain.session import ReasoningConfiguration, Session, SessionState


@pytest.fixture
def command() -> TemperatureCommand:
    return TemperatureCommand()

@pytest.fixture
def mock_session() -> Mock:
    mock = Mock(spec=Session)
    mock.state = SessionState(reasoning_config=ReasoningConfiguration())
    return mock

@pytest.mark.asyncio
async def test_temperature_success(command: TemperatureCommand, mock_session: Mock):
    # Arrange
    args = {"value": "0.75"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is True
    assert result.message == "Temperature set to 0.75"
    assert result.new_state is not None
    assert result.new_state.reasoning_config.temperature == 0.75

@pytest.mark.asyncio
async def test_temperature_failure_invalid_number(command: TemperatureCommand, mock_session: Mock):
    # Arrange
    args = {"value": "abc"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert result.message == "Temperature must be a valid number"

@pytest.mark.asyncio
async def test_temperature_failure_out_of_range(command: TemperatureCommand, mock_session: Mock):
    # Arrange
    args = {"value": "-1.0"}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert result.message == "Temperature must be between 0.0 and 1.0"

@pytest.mark.asyncio
async def test_temperature_failure_no_value(command: TemperatureCommand, mock_session: Mock):
    # Arrange
    args = {"value": None}

    # Act
    result = await command.execute(args, mock_session)

    # Assert
    assert result.success is False
    assert result.message == "Temperature value must be specified"
