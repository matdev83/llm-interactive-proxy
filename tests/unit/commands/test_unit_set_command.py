from unittest.mock import Mock

import pytest
from src.core.domain.commands.set_command import SetCommand
from src.core.domain.session import (
    BackendConfiguration,
    ReasoningConfiguration,
    Session,
    SessionState,
)


@pytest.fixture
def command() -> SetCommand:
    """Returns a new instance of the SetCommand for each test."""
    from src.core.services.application_state_service import ApplicationStateService
    from src.core.services.secure_state_service import SecureStateService

    # Create mock state services for testing
    app_state = ApplicationStateService()
    secure_state = SecureStateService(app_state)

    return SetCommand(state_reader=secure_state, state_modifier=secure_state)


@pytest.fixture
def mock_session() -> Mock:
    """Creates a mock session object with a default state.

    This fixture demonstrates the traditional approach. For new tests,
    consider using the safe_session_service fixture to prevent coroutine warnings.
    """
    mock = Mock(spec=Session)
    mock.state = SessionState(
        backend_config=BackendConfiguration(
            backend_type="test_backend", model="test_model"
        ),
        reasoning_config=ReasoningConfiguration(temperature=0.5),
        project=None,
    )
    return mock


@pytest.fixture
def safe_mock_session(mock_session):
    """Creates a safe session using the existing mock session fixture.

    This demonstrates the recommended approach using standard mocking.
    """
    return mock_session


@pytest.mark.asyncio
async def test_handle_temperature_success(
    command: SetCommand, mock_session: Mock
) -> None:
    # Arrange
    value = "0.8"

    # Act
    result, new_state = await command._handle_temperature(value, mock_session.state, {})

    # Assert
    assert result.success is True
    assert result.message == "Temperature set to 0.8"
    assert new_state.reasoning_config.temperature == 0.8


@pytest.mark.asyncio
async def test_handle_temperature_invalid_value(
    command: SetCommand, mock_session: Mock
) -> None:
    # Arrange
    value = "invalid"

    # Act
    result, _ = await command._handle_temperature(value, mock_session.state, {})

    # Assert
    assert result.success is False
    assert result.message == "Temperature must be a valid number"


@pytest.mark.asyncio
async def test_handle_temperature_out_of_range(
    command: SetCommand, mock_session: Mock
) -> None:
    # Arrange
    value = "2.0"

    # Act
    result, _ = await command._handle_temperature(value, mock_session.state, {})

    # Assert
    assert result.success is False
    assert result.message == "Temperature must be between 0.0 and 1.0"


@pytest.mark.asyncio
async def test_handle_backend_and_model_set_backend(
    command: SetCommand, mock_session: Mock
) -> None:
    # Arrange
    args = {"backend": "new_backend"}

    # Act
    result, new_state = await command._handle_backend_and_model(
        args, mock_session.state, context={}
    )

    # Assert
    assert result.success is True
    assert "Backend changed to new_backend" in result.message
    assert new_state.backend_config.backend_type == "new_backend"


@pytest.mark.asyncio
async def test_handle_backend_and_model_set_model(
    command: SetCommand, mock_session: Mock
) -> None:
    # Arrange
    args = {"model": "new_model"}

    # Act
    result, new_state = await command._handle_backend_and_model(
        args, mock_session.state, context={}
    )

    # Assert
    assert result.success is True
    assert "Model changed to new_model" in result.message
    assert new_state.backend_config.model == "new_model"


@pytest.mark.asyncio
async def test_handle_backend_and_model_set_both(
    command: SetCommand, mock_session: Mock
) -> None:
    # Arrange
    args = {"model": "another_backend:another_model"}

    # Act
    result, new_state = await command._handle_backend_and_model(
        args, mock_session.state, context={}
    )

    # Assert
    assert result.success is True
    assert "Backend changed to another_backend" in result.message
    assert "Model changed to another_model" in result.message
    assert new_state.backend_config.backend_type == "another_backend"
    assert new_state.backend_config.model == "another_model"


@pytest.mark.asyncio
async def test_handle_interactive_mode_disable_updates_state(
    command: SetCommand, mock_session: Mock
) -> None:
    result, new_state = await command._handle_interactive_mode(
        "off", mock_session.state, {}
    )

    assert result.success is True
    assert result.message == "Interactive mode disabled"
    assert result.data == {"interactive-mode": False}
    assert new_state.backend_config.interactive_mode is False
    assert new_state.interactive_just_enabled is False


@pytest.mark.asyncio
async def test_handle_interactive_mode_enable_updates_state(
    command: SetCommand,
) -> None:
    initial_state = SessionState(
        backend_config=BackendConfiguration(
            backend_type="test_backend", model="test_model", interactive_mode=False
        ),
        reasoning_config=ReasoningConfiguration(temperature=0.5),
    )

    result, new_state = await command._handle_interactive_mode("on", initial_state, {})

    assert result.success is True
    assert result.message == "Interactive mode enabled"
    assert result.data == {"interactive-mode": True}
    assert new_state.backend_config.interactive_mode is True
    assert new_state.interactive_just_enabled is True


@pytest.mark.asyncio
async def test_handle_project_success(command: SetCommand, mock_session: Mock) -> None:
    # Arrange
    value = "test_project"

    # Act
    result, new_state = await command._handle_project(value, mock_session.state, {})

    # Assert
    assert result.success is True
    assert result.message == "Project changed to test_project"
    assert new_state.project == "test_project"


@pytest.mark.asyncio
async def test_handle_temperature_with_safe_session(
    command: SetCommand, safe_mock_session: Mock
) -> None:
    """Demonstrates using the safe session service to prevent coroutine warnings."""
    # Arrange
    value = "0.9"

    # Act
    result, new_state = await command._handle_temperature(
        value, safe_mock_session.state, {}
    )

    # Assert
    assert result.success is True
    assert result.message == "Temperature set to 0.9"
    assert new_state.reasoning_config.temperature == 0.9

    # This test demonstrates using the standard mock_session fixture
    # which provides consistent behavior without coroutine warnings
