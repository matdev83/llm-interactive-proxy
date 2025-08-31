from typing import Any
from unittest.mock import MagicMock

import pytest
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
async def run_command(command_string: str, initial_state: SessionState = None) -> str:
    """Run a command and return the result message."""
    from src.core.commands.parser import CommandParser
    from src.core.commands.service import NewCommandService
    from src.core.domain.chat import ChatMessage
    from src.core.services.command_processor import (
        CommandProcessor as CoreCommandProcessor,
    )
    from tests.unit.core.test_doubles import MockSessionService

    # Create a Session object to hold the state
    initial_state = initial_state or SessionState()
    session = Session(session_id="test_session", state=initial_state)

    session_service = MockSessionService(session=session)
    command_parser = CommandParser()
    service = NewCommandService(session_service, command_parser)
    processor = CoreCommandProcessor(service)

    messages = [ChatMessage(role="user", content=command_string)]

    result = await processor.process_messages(messages, session_id="test_session")

    if result.command_results:
        return result.command_results[0].message

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
    snapshot.assert_match(output_message, "unset_temperature_output")


@pytest.mark.asyncio
async def test_unset_model_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting the model."""
    # Arrange
    command_string = "!/unset(model)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    snapshot.assert_match(output_message, "unset_model_output")


@pytest.mark.asyncio
async def test_unset_multiple_params_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting multiple parameters at once."""
    # Arrange
    command_string = "!/unset(project, temperature)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    snapshot.assert_match(output_message, "unset_multiple_params_output")


@pytest.mark.asyncio
async def test_unset_unknown_param_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting an unknown parameter."""
    # Arrange
    command_string = "!/unset(nonexistent)"

    # Act
    output_message = await run_command(command_string, initial_state)

    # Assert
    snapshot.assert_match(output_message, "unset_unknown_param_output")
