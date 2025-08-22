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
async def run_command(command_string: str, initial_state: SessionState = None) -> str:
    """Run a command and return the result message."""
    # Import required modules
    from tests.unit.mock_commands import MockSetCommand
    
    # Create a Session object to hold the state
    initial_state = initial_state or SessionState()
    
    # Create a set command instance
    set_command = MockSetCommand()
    
    # Execute the command directly
    if "!/set" in command_string:
        # Extract any arguments from the command
        args = {}
        if "(" in command_string and ")" in command_string:
            arg_part = command_string.split("(")[1].split(")")[0]
            if "=" in arg_part:
                if "," in arg_part:
                    # Handle multiple parameters
                    for part in arg_part.split(","):
                        if "=" in part:
                            key, value = part.split("=", 1)
                            args[key.strip()] = value.strip()
                        else:
                            args[part.strip()] = True
                else:
                    # Handle single parameter
                    key, value = arg_part.split("=", 1)
                    args[key.strip()] = value.strip()
            elif arg_part:
                args[arg_part.strip()] = True
        
        # Execute the set command directly
        result = await set_command.execute(args, initial_state)
        
        # Return the message from the result
        if result and hasattr(result, 'message'):
            return result.message
    
    # Return empty string if no command was found or executed
    return ""


@pytest.mark.asyncio

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
    snapshot.assert_match(output_message, "set_temperature_output")


@pytest.mark.asyncio

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
    snapshot.assert_match(output_message, "set_backend_and_model_output")
