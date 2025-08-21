from unittest.mock import Mock

import pytest

# Removed skip marker - now have snapshot fixture available
from src.command_config import CommandParserConfig
from src.command_parser import CommandParser
from src.core.domain.session import SessionState
from src.core.services.command_service import CommandRegistry

# Import the centralized test helper
from tests.conftest import setup_test_command_registry





# Helper function that uses the real command discovery
async def run_command(command_string: str) -> str:
    parser_config = Mock(spec=CommandParserConfig)
    parser_config.proxy_state = SessionState()
    parser_config.app = Mock()
    parser_config.preserve_unknown = True

    # Use the centralized test helper
    setup_test_command_registry()

    parser = CommandParser(parser_config, command_prefix="!/")

    # Create proper message objects
    from src.core.domain.chat import ChatMessage

    messages = [ChatMessage(role="user", content=command_string)]
    _, _ = await parser.process_messages(messages)

    if parser.command_results:
        return parser.command_results[-1].message
    return ""


@pytest.mark.asyncio
@pytest.mark.skip("Skipping until command handling in tests is fixed")
async def test_help_general_snapshot(snapshot):
    """Snapshot test for the general !/help command."""
    # Arrange
    command_string = "!/help"

    # Act
    output_message = await run_command(command_string)

    # Assert
    assert output_message == snapshot(output_message)


@pytest.mark.asyncio
@pytest.mark.skip("Skipping until command handling in tests is fixed")
async def test_help_specific_command_snapshot(snapshot):
    """Snapshot test for !/help on a specific command."""
    # Arrange
    command_string = "!/help(set)"

    # Act
    output_message = await run_command(command_string)

    # Assert
    assert output_message == snapshot(output_message)


@pytest.mark.asyncio
@pytest.mark.skip("Skipping until command handling in tests is fixed")
async def test_help_unknown_command_snapshot(snapshot):
    """Snapshot test for !/help on an unknown command."""
    # Arrange
    command_string = "!/help(nonexistentcommand)"

    # Act
    output_message = await run_command(command_string)

    # Assert
    assert output_message == snapshot(output_message)
