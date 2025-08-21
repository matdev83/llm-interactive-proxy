from unittest.mock import Mock, patch, MagicMock
from typing import Any, cast

import pytest

from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.chat import ChatMessage
from src.core.domain.commands.set_command import SetCommand
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


# Helper function to simulate running a command
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
    parser_config.proxy_state = session.state  # Use the state from the session
    parser_config.app = mock_app  # Pass the mock app
    parser_config.functional_backends = {
        "test_backend"
    }  # Add a functional backend for tests
    parser_config.preserve_unknown = True

    parser = CommandParser(parser_config, command_prefix="!/")

    # Manually register the command we are testing
    parser.register_command(SetCommand(mock_session_service, mock_session_service))

    # The parser returns a list of messages and a boolean.
    # We are interested in the content of the processed message.
    # In the case of a pure command, the message list is often empty,
    # and the result is in parser.command_results
    _, _ = await parser.process_messages(
        [ChatMessage(role="user", content=command_string)]
    )

    if parser.command_results:
        return parser.command_results[-1].message
    return ""


@pytest.mark.asyncio
@pytest.mark.skip("Skipping until command handling in tests is fixed")
async def test_set_temperature_integration(snapshot):
    """
    Integration test for the SetCommand using snapshot testing.
    This test verifies the final user-facing output message.
    """
    # Arrange
    initial_reasoning_config = ReasoningConfiguration(temperature=0.5)
    initial_backend_config = BackendConfiguration(
        backend_type="test_backend", model="test_model"
    )
    initial_state = SessionState(
        backend_config=initial_backend_config, reasoning_config=initial_reasoning_config
    )

    command_string = "!/set(temperature=0.8)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    assert output_message == snapshot(output_message)


@pytest.mark.asyncio
@pytest.mark.skip("Skipping until command handling in tests is fixed")
async def test_set_backend_and_model_integration(snapshot):
    """
    Integration test for setting backend and model together.
    """
    # Arrange
    initial_reasoning_config = ReasoningConfiguration(temperature=0.5)
    initial_backend_config = BackendConfiguration(
        backend_type="initial_backend", model="initial_model"
    )
    initial_state = SessionState(
        backend_config=initial_backend_config, reasoning_config=initial_reasoning_config
    )

    command_string = "!/set(model=test_backend:new_model)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    assert output_message == snapshot(output_message)
