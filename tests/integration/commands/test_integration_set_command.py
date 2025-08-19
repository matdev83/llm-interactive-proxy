
import pytest
from unittest.mock import Mock
from src.core.domain.commands.set_command import SetCommand
from src.core.domain.session import Session, SessionState, BackendConfiguration, ReasoningConfiguration
from src.command_parser import CommandParser
from src.command_config import CommandParserConfig

# Helper function to simulate running a command
async def run_command(command_string: str, initial_state: SessionState) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = initial_state
    parser_config.app = Mock()
    parser_config.functional_backends = {"test_backend"} # Add a functional backend for tests
    parser_config.preserve_unknown = True

    parser = CommandParser(parser_config, command_prefix="!/")
    
    # Manually register the command we are testing
    parser.register_command(SetCommand())
    
    # The parser returns a list of messages and a boolean.
    # We are interested in the content of the processed message.
    # In the case of a pure command, the message list is often empty, 
    # and the result is in parser.command_results
    _, _ = await parser.process_messages([{"role": "user", "content": command_string}])
    
    if parser.command_results:
        return parser.command_results[-1].message
    return ""

@pytest.mark.asyncio
async def test_set_temperature_integration(snapshot):
    """
    Integration test for the SetCommand using snapshot testing.
    This test verifies the final user-facing output message.
    """
    # Arrange
    initial_reasoning_config = ReasoningConfiguration(temperature=0.5)
    initial_backend_config = BackendConfiguration(backend_type="test_backend", model="test_model")
    initial_state = SessionState(backend_config=initial_backend_config, reasoning_config=initial_reasoning_config)
    
    command_string = "!/set(temperature=0.8)"
    
    # Act
    output_message = await run_command(command_string, initial_state)
    
    # Assert
    assert output_message == snapshot

@pytest.mark.asyncio
async def test_set_backend_and_model_integration(snapshot):
    """
    Integration test for setting backend and model together.
    """
    # Arrange
    initial_reasoning_config = ReasoningConfiguration(temperature=0.5)
    initial_backend_config = BackendConfiguration(backend_type="initial_backend", model="initial_model")
    initial_state = SessionState(backend_config=initial_backend_config, reasoning_config=initial_reasoning_config)
    
    command_string = "!/set(model=test_backend:new_model)"
    
    # Act
    output_message = await run_command(command_string, initial_state)
    
    # Assert
    assert output_message == snapshot
