
from unittest.mock import Mock

import pytest
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.session import SessionState


# Helper function that uses the real command discovery
async def run_command(command_string: str) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = SessionState()
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    # This is the key difference: we use the actual auto-discovery
    # to ensure the help command reports on all real commands.
    parser = CommandParser(parser_config, command_prefix="!/")
    
    _, _ = await parser.process_messages([{"role": "user", "content": command_string}])
    
    if parser.command_results:
        return parser.command_results[-1].message
    return ""

@pytest.mark.asyncio
async def test_help_general_snapshot(snapshot):
    """Snapshot test for the general !/help command."""
    # Arrange
    command_string = "!/help"
    
    # Act
    output_message = await run_command(command_string)
    
    # Assert
    assert output_message == snapshot

@pytest.mark.asyncio
async def test_help_specific_command_snapshot(snapshot):
    """Snapshot test for !/help on a specific command."""
    # Arrange
    command_string = "!/help(set)"
    
    # Act
    output_message = await run_command(command_string)
    
    # Assert
    assert output_message == snapshot

@pytest.mark.asyncio
async def test_help_unknown_command_snapshot(snapshot):
    """Snapshot test for !/help on an unknown command."""
    # Arrange
    command_string = "!/help(nonexistentcommand)"
    
    # Act
    output_message = await run_command(command_string)
    
    # Assert
    assert output_message == snapshot
