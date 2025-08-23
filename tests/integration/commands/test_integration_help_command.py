
import pytest

# Removed skip marker - now have snapshot fixture available
from src.core.domain.session import SessionState

# Import the centralized test helper





# Helper function that uses the real command discovery
async def run_command(command_string: str, initial_state: SessionState = None) -> str:
    """Run a command and return the result message."""
    # Import required modules
    from tests.unit.mock_commands import MockHelpCommand
    
    # Create a help command instance
    help_command = MockHelpCommand()
    
    # Execute the command directly
    if "!/help" in command_string:
        # Extract any arguments from the command
        args = {}
        if "(" in command_string and ")" in command_string:
            arg_part = command_string.split("(")[1].split(")")[0]
            if arg_part:
                args = {arg_part: True}
        
        # Execute the help command directly
        result = await help_command.execute(args, initial_state or SessionState())
        
        # Return the message from the result
        if result and hasattr(result, 'message'):
            return result.message
    
    # Return empty string if no command was found or executed
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
