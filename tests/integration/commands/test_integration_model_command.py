import pytest

# Removed skip marker - now have snapshot fixture available
from src.core.domain.session import SessionState

# Import the centralized test helper


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
