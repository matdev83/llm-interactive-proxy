"""Tests for the command service implementation."""

from unittest.mock import AsyncMock

import pytest
from src.core.commands.handler_factory import CommandHandlerFactory
from src.core.domain.chat import ChatMessage
from src.core.domain.configuration import (
    BackendConfig,
    LoopDetectionConfig,
    ReasoningConfig,
)
from src.core.domain.session import Session, SessionState
from src.core.services.command_service import CommandRegistry, CommandService


@pytest.fixture
def command_registry():
    """Create a command registry with registered handlers."""
    registry = CommandRegistry()
    factory = CommandHandlerFactory()
    for handler in factory.create_handlers():
        registry.register(handler)
    return registry


@pytest.fixture
def session():
    """Create a test session."""
    backend_config = BackendConfig(
        backend_type="openrouter",
        model="gpt-3.5-turbo",
        interactive_mode=True,
    )
    reasoning_config = ReasoningConfig(
        reasoning_effort="low",
        thinking_budget=0,
        temperature=0.7,
    )
    loop_config = LoopDetectionConfig(
        loop_detection_enabled=True,
        tool_loop_detection_enabled=True,
        min_pattern_length=50,
        max_pattern_length=500,
    )
    state = SessionState(
        backend_config=backend_config,
        reasoning_config=reasoning_config,
        loop_config=loop_config,
        project="test-project",
    )
    return Session(session_id="test-session", state=state)


@pytest.fixture
def session_service(session):
    """Create a mock session service."""
    mock_service = AsyncMock()
    mock_service.get_session = AsyncMock(return_value=session)
    return mock_service


@pytest.fixture
def command_service(command_registry, session_service):
    """Create a command service for testing."""
    return CommandService(command_registry, session_service)


@pytest.mark.asyncio
async def test_model_command(command_service):
    """Test the model command."""
    messages = [ChatMessage(role="user", content="!/model(name=gpt-4)")]

    # Process the command
    result = await command_service.process_commands(messages, "test-session")

    # Verify the result
    assert result.command_executed
    assert len(result.command_results) == 1
    assert result.command_results[0].success
    assert "gpt-4" in result.command_results[0].message

    # Verify the message was modified
    assert result.modified_messages[0].content == ""


@pytest.mark.asyncio
async def test_temperature_command(command_service):
    """Test the temperature command."""
    messages = [ChatMessage(role="user", content="!/temperature(value=0.9)")]

    # Process the command
    result = await command_service.process_commands(messages, "test-session")

    # Verify the result
    assert result.command_executed
    assert len(result.command_results) == 1
    assert result.command_results[0].success
    assert "0.9" in result.command_results[0].message

    # Verify the message was modified
    assert result.modified_messages[0].content == ""


@pytest.mark.asyncio
async def test_project_command(command_service):
    """Test the project command."""
    messages = [ChatMessage(role="user", content="!/project(name=new-project)")]

    # Process the command
    result = await command_service.process_commands(messages, "test-session")

    # Verify the result
    assert result.command_executed
    assert len(result.command_results) == 1
    assert result.command_results[0].success
    assert "new-project" in result.command_results[0].message

    # Verify the message was modified
    assert result.modified_messages[0].content == ""


@pytest.mark.asyncio
async def test_help_command(command_service):
    """Test the help command."""
    messages = [ChatMessage(role="user", content="!/help")]

    # Process the command
    result = await command_service.process_commands(messages, "test-session")

    # Verify the result
    assert result.command_executed
    assert len(result.command_results) == 1
    assert result.command_results[0].success
    assert "Available commands" in result.command_results[0].message

    # Verify the message was modified
    assert result.modified_messages[0].content == ""


@pytest.mark.asyncio
async def test_help_command_with_specific_command(command_service):
    """Test the help command for a specific command."""
    messages = [ChatMessage(role="user", content="!/help(command=model)")]

    # Process the command
    result = await command_service.process_commands(messages, "test-session")

    # Verify the result
    assert result.command_executed
    assert len(result.command_results) == 1
    assert result.command_results[0].success
    assert "Help for model" in result.command_results[0].message

    # Verify the message was modified
    assert result.modified_messages[0].content == ""


@pytest.mark.asyncio
async def test_unknown_command(command_service):
    """Test an unknown command."""
    messages = [ChatMessage(role="user", content="!/nonexistent")]

    # Process the command
    result = await command_service.process_commands(messages, "test-session")

    # Verify the result
    assert not result.command_executed
    assert len(result.command_results) == 0

    # Verify the message was modified
    assert result.modified_messages[0].content == " "


@pytest.mark.asyncio
async def test_command_with_remaining_text(command_service):
    """Test a command with remaining text."""
    messages = [
        ChatMessage(role="user", content="!/model(name=gpt-4) Tell me about AI")
    ]

    # Process the command
    result = await command_service.process_commands(messages, "test-session")

    # Verify the result
    assert result.command_executed
    assert len(result.command_results) == 1
    assert result.command_results[0].success

    # Verify the message was modified to keep remaining text
    assert result.modified_messages[0].content == " Tell me about AI"
