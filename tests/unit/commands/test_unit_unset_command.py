import pytest
from src.core.domain.commands.unset_command import UnsetCommand
from src.core.domain.session import (
    BackendConfiguration,
    ReasoningConfiguration,
    SessionState,
)


@pytest.fixture
def command() -> UnsetCommand:
    """Returns a new instance of the UnsetCommand for each test."""
    return UnsetCommand()


@pytest.fixture
def initial_state() -> SessionState:
    """Returns a default SessionState for tests."""
    return SessionState(
        backend_config=BackendConfiguration(
            backend_type="test_backend",
            model="test_model",
            override_backend="custom_backend",
            override_model="custom_model",
        ),
        reasoning_config=ReasoningConfiguration(temperature=0.9),
        project="test_project",
    )


def test_unset_backend(command: UnsetCommand, initial_state: SessionState):
    # Act
    result, new_state = command._unset_backend(initial_state, {})

    # Assert
    assert result.success is True
    assert result.message == "Backend reset to default"
    assert new_state.backend_config.backend_type is None


def test_unset_model(command: UnsetCommand, initial_state: SessionState):
    # Act
    result, new_state = command._unset_model(initial_state, {})

    # Assert
    assert result.success is True
    assert result.message == "Model reset to default"
    assert new_state.backend_config.model is None


def test_unset_temperature(command: UnsetCommand, initial_state: SessionState):
    # Act
    result, new_state = command._unset_temperature(initial_state, {})

    # Assert
    default_temp = ReasoningConfiguration().temperature
    assert result.success is True
    assert result.message == f"Temperature reset to default ({default_temp})"
    assert new_state.reasoning_config.temperature == default_temp


def test_unset_project(command: UnsetCommand, initial_state: SessionState):
    # Act
    result, new_state = command._unset_project(initial_state, {})

    # Assert
    assert result.success is True
    assert result.message == "Project reset to default"
    assert new_state.project is None
