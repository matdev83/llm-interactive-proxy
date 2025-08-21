from unittest.mock import Mock, MagicMock
from typing import Any, cast

import pytest

from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.chat import ChatMessage
from src.core.domain.session import (
    BackendConfiguration,
    ReasoningConfiguration,
    Session,
    SessionState,
)
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)


class MockSessionService(ISecureStateAccess, ISecureStateModification):
    def __init__(self, mock_app: MagicMock, session: Session):
        self._mock_app = mock_app
        self._session = session

    # ISecureStateAccess methods
    def get_command_prefix(self) -> str | None:
        return self._mock_app.state.command_prefix

    def get_api_key_redaction_enabled(self) -> bool:
        return self._mock_app.state.api_key_redaction_enabled

    def get_disable_interactive_commands(self) -> bool:
        return self._mock_app.state.disable_interactive_commands

    def get_failover_routes(self) -> list[dict[str, Any]] | None:
        return self._mock_app.state.failover_routes

    # ISecureStateModification methods
    def update_command_prefix(self, prefix: str) -> None:
        self._mock_app.state.command_prefix = prefix

    def update_api_key_redaction(self, enabled: bool) -> None:
        self._mock_app.state.api_key_redaction_enabled = enabled

    def update_interactive_commands(self, disabled: bool) -> None:
        self._mock_app.state.disable_interactive_commands = disabled

    def update_failover_routes(self, routes: list[dict[str, Any]]) -> None:
        self._mock_app.state.failover_routes = routes


# Helper function to simulate running a command, adapted for unset command tests
async def run_command(command_string: str, initial_state: SessionState) -> str:
    # Create a Session object to hold the state
    session = Session(session_id="test_session", state=initial_state)

    # Create a mock app and its state
    mock_app = MagicMock()
    mock_app.state = MagicMock()
    mock_app.state.command_prefix = "!/"  # Default value
    mock_app.state.api_key_redaction_enabled = False  # Default value
    mock_app.state.disable_interactive_commands = False  # Default value
    mock_app.state.failover_routes = []  # Default value

    # Create the mock session service
    mock_session_service = MockSessionService(mock_app, session)

    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = session.state
    parser_config.app = mock_app
    parser_config.functional_backends = {
        "test_backend"
    }  # Add a functional backend for tests
    parser_config.preserve_unknown = True

    parser = CommandParser(parser_config, command_prefix="!/")

    # Manually register the command we are testing
    from src.core.domain.commands.unset_command import UnsetCommand
    parser.handlers = {"unset": UnsetCommand(mock_session_service, mock_session_service)}  # Manually insert handler

    _, _ = await parser.process_messages(
        [ChatMessage(role="user", content=command_string)]
    )

    if parser.command_results:
        return parser.command_results[-1].message
    return ""


@pytest.fixture
def initial_state() -> SessionState:
    """Provides a session state with non-default values to be unset."""
    return SessionState(
        backend_config=BackendConfiguration(
            backend_type="default_backend",
            model="default_model",
            override_backend="custom_backend",
            override_model="custom_model",
        ),
        reasoning_config=ReasoningConfiguration(temperature=0.9),
        project="test_project",
    )


@pytest.mark.asyncio
async def test_unset_temperature_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting temperature."""
    # Arrange
    command_string = "!/unset(temperature)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    assert output_message == snapshot(output_message)


@pytest.mark.asyncio
async def test_unset_model_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting the model."""
    # Arrange
    command_string = "!/unset(model)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    assert output_message == snapshot(output_message)


@pytest.mark.asyncio
async def test_unset_multiple_params_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting multiple parameters at once."""
    # Arrange
    command_string = "!/unset(project, temperature)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    assert output_message == snapshot(output_message)


@pytest.mark.asyncio
async def test_unset_unknown_param_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting an unknown parameter."""
    # Arrange
    command_string = "!/unset(nonexistent)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    assert output_message == snapshot(output_message)
