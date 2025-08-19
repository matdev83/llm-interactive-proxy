
from unittest.mock import Mock

import pytest
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.session import (
    BackendConfiguration,
    ReasoningConfiguration,
    SessionState,
)


# Helper function to simulate running a command, adapted for unset command tests
async def run_command(command_string: str, initial_state: SessionState) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = initial_state
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    # In a real scenario, the parser would auto-discover commands.
    # For this test, we manually register the command to keep the test isolated.
    from src.core.domain.commands.unset_command import UnsetCommand
    parser = CommandParser(parser_config, command_prefix="!/")
    parser.handlers = {"unset": UnsetCommand()} # Manually insert handler
    
    _, _ = await parser.process_messages([{"role": "user", "content": command_string}])
    
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
            override_model="custom_model"
        ),
        reasoning_config=ReasoningConfiguration(temperature=0.9),
        project="test_project"
    )

@pytest.mark.asyncio
async def test_unset_temperature_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting temperature."""
    # Arrange
    command_string = "!/unset(temperature)"
    
    # Act
    output_message = await run_command(command_string, initial_state)
    
    # Assert
    assert output_message == snapshot

@pytest.mark.asyncio
async def test_unset_model_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting the model."""
    # Arrange
    command_string = "!/unset(model)"
    
    # Act
    output_message = await run_command(command_string, initial_state)
    
    # Assert
    assert output_message == snapshot

@pytest.mark.asyncio
async def test_unset_multiple_params_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting multiple parameters at once."""
    # Arrange
    command_string = "!/unset(project, temperature)"
    
    # Act
    output_message = await run_command(command_string, initial_state)
    
    # Assert
    assert output_message == snapshot

@pytest.mark.asyncio
async def test_unset_unknown_param_snapshot(initial_state: SessionState, snapshot):
    """Snapshot test for unsetting an unknown parameter."""
    # Arrange
    command_string = "!/unset(nonexistent)"
    
    # Act
    output_message = await run_command(command_string, initial_state)
    
    # Assert
    assert output_message == snapshot
