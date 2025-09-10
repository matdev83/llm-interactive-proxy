import pytest

# Removed skip marker - now have snapshot fixture available
from src.core.domain.session import SessionState

# Import the centralized test helper


# Helper function that uses the real command discovery
async def run_command(command_string: str, initial_state: SessionState = None) -> str:
    """Run a command and return the result message."""
    from src.core.commands.parser import CommandParser
    from src.core.commands.service import NewCommandService
    from src.core.domain.chat import ChatMessage
    from src.core.domain.session import Session
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


@pytest.mark.asyncio
async def test_help_general_snapshot(snapshot):
    """Snapshot test for the general !/help command."""
    # Arrange
    command_string = "!/help"

    # Act
    output_message = await run_command(command_string)

    # Assert
    snapshot.assert_match(output_message, "help_general_output")


@pytest.mark.asyncio
async def test_help_specific_command_snapshot(snapshot):
    """Snapshot test for !/help on a specific command."""
    # Arrange
    command_string = "!/help(set)"

    # Act
    output_message = await run_command(command_string)

    # Assert
    snapshot.assert_match(output_message, "help_specific_command_output")


@pytest.mark.asyncio
async def test_help_unknown_command_snapshot(snapshot):
    """Snapshot test for !/help on an unknown command."""
    # Arrange
    command_string = "!/help(nonexistentcommand)"

    # Act
    output_message = await run_command(command_string)

    # Assert
    snapshot.assert_match(output_message, "help_unknown_command_output")
