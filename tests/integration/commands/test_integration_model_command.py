import pytest

# Removed skip marker - now have snapshot fixture available
from src.core.domain.session import BackendConfiguration, SessionState

# Import the centralized test helper


async def run_command(command_string: str, initial_state: SessionState = None) -> str:
    """Run a command and return the result message."""
    # Import required modules
    from tests.unit.mock_commands import MockModelCommand

    # Create a model command instance
    model_command = MockModelCommand()

    # Execute the command directly
    if "!/model" in command_string:
        # Extract any arguments from the command
        args = {}
        if "(" in command_string and ")" in command_string:
            arg_part = command_string.split("(")[1].split(")")[0]
            if "=" in arg_part:
                key, value = arg_part.split("=", 1)
                args[key.strip()] = value.strip()
            elif arg_part:
                args[arg_part.strip()] = True

        # Execute the model command directly
        result = await model_command.execute(
            args, initial_state or SessionState(backend_config=BackendConfiguration())
        )

        # Return the message from the result
        if result and hasattr(result, "message"):
            return result.message

    # Return empty string if no command was found or executed
    return ""


@pytest.mark.asyncio
async def test_set_model_snapshot(snapshot):
    """Snapshot test for setting a model."""
    command_string = "!/model(name=gpt-4-turbo)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "model_set_output")


@pytest.mark.asyncio
async def test_set_model_with_backend_snapshot(snapshot):
    """Snapshot test for setting a model with a backend."""
    command_string = "!/model(name=openrouter:claude-3-opus)"
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "model_set_with_backend_output")


@pytest.mark.asyncio
async def test_unset_model_snapshot(snapshot):
    """Snapshot test for unsetting a model."""
    command_string = "!/model(name=)"  # Unset by providing an empty name
    output_message = await run_command(command_string)
    snapshot.assert_match(output_message, "model_unset_output")
