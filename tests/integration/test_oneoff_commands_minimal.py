"""
Minimal unit tests for oneoff command functionality.
Tests the core command logic without complex integration setup.
"""

import pytest


@pytest.mark.asyncio
@pytest.mark.skip("Skipping until command handling in tests is fixed")
async def test_oneoff_command_parsing():
    """Test that oneoff commands can be parsed correctly."""
    from src.command_parser import process_commands_in_messages
    from src.core.domain.chat import ChatMessage
    from src.core.domain.session import Session

    # Create a simple session
    session = Session(session_id="test-session")

    # Test message with oneoff command
    messages = [
        ChatMessage(role="user", content="!/oneoff(openai/gpt-4)\nWhat is AI?")
    ]

    # This should process the command and return modified messages
    processed_messages, commands_processed = await process_commands_in_messages(
        messages, session.state, command_prefix="!/"
    )

    # Verify command was processed
    assert commands_processed
    assert len(processed_messages) == 1

    # The command should be removed and only the remaining text should be left
    assert processed_messages[0].content == "What is AI?"
    assert processed_messages[0].role == "user"


@pytest.mark.asyncio
async def test_oneoff_command_execution():
    """Test that oneoff commands execute and modify session state."""
    from src.core.domain.commands.oneoff_command import OneoffCommand
    from src.core.domain.session import Session

    # Create session and command
    session = Session(session_id="test-session")
    command = OneoffCommand()

    # Execute the command
    result = await command.execute({"openai/gpt-4": True}, session)

    # Verify command succeeded
    assert result.success
    assert "One-off route set to openai/gpt-4" in result.message

    # Verify session state was updated
    assert session.state.backend_config.oneoff_backend == "openai"
    assert session.state.backend_config.oneoff_model == "gpt-4"


@pytest.mark.asyncio
async def test_oneoff_command_invalid_format():
    """Test error handling for invalid oneoff command formats."""
    from src.core.domain.commands.oneoff_command import OneoffCommand
    from src.core.domain.session import Session

    session = Session(session_id="test-session")
    command = OneoffCommand()

    # Test with invalid format
    result = await command.execute({"invalid-format": True}, session)

    # Should fail with error message
    assert not result.success
    assert "Invalid format" in result.message


@pytest.mark.asyncio
async def test_oneoff_command_missing_argument():
    """Test error handling for oneoff command with no argument."""
    from src.core.domain.commands.oneoff_command import OneoffCommand
    from src.core.domain.session import Session

    session = Session(session_id="test-session")
    command = OneoffCommand()

    # Test with no arguments
    result = await command.execute({}, session)

    # Should fail with error message
    assert not result.success
    assert "requires a backend/model argument" in result.message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
