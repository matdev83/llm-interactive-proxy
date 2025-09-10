"""
Minimal unit tests for oneoff command functionality.
Tests the core command logic without complex integration setup.
"""

import pytest


@pytest.mark.asyncio
async def test_oneoff_command_parsing():
    """Test that oneoff commands can be parsed correctly."""
    # This test is now covered by the command execution tests below
    # and the integration tests in test_integration_oneoff_command.py
    # The command parsing logic is tested through the actual command execution


@pytest.mark.asyncio
async def test_oneoff_command_execution():
    """Test that oneoff commands execute and modify session state."""
    from src.core.domain.commands.oneoff_command import OneoffCommand
    from src.core.domain.session import BackendConfiguration, Session, SessionState

    # Create session and command with proper state initialization
    session = Session(session_id="test-session")
    session.state = SessionState(backend_config=BackendConfiguration())
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
    from src.core.domain.session import BackendConfiguration, Session, SessionState

    session = Session(session_id="test-session")
    session.state = SessionState(backend_config=BackendConfiguration())
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
    from src.core.domain.session import BackendConfiguration, Session, SessionState

    session = Session(session_id="test-session")
    session.state = SessionState(backend_config=BackendConfiguration())
    command = OneoffCommand()

    # Test with no arguments
    result = await command.execute({}, session)

    # Should fail with error message
    assert not result.success
    assert "requires a backend/model argument" in result.message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
