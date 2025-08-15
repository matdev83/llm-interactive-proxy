"""
Tests for the CommandService implementation.
"""


import pytest
from src.commands.base import BaseCommand, CommandResult
from src.core.services.command_service import CommandRegistry, CommandService

from tests.unit.core.test_doubles import MockSessionService


class MockCommand(BaseCommand):
    """Mock command for testing."""
    
    def __init__(self, name, success=True, message="Command executed"):
        self.name = name
        self._success = success
        self._message = message
        self.called = False
        self.args = None
        self.proxy_state = None
        
    def execute(self, args, proxy_state, app):
        self.called = True
        self.args = args
        self.proxy_state = proxy_state
        return CommandResult(self.name, self._success, self._message)


@pytest.mark.asyncio
async def test_command_registry():
    """Test the command registry."""
    # Arrange
    registry = CommandRegistry()
    cmd1 = MockCommand("test1")
    cmd2 = MockCommand("test2")
    
    # Act
    registry.register(cmd1)
    registry.register(cmd2)
    
    # Assert
    assert registry.get("test1") == cmd1
    assert registry.get("test2") == cmd2
    assert registry.get("nonexistent") is None
    
    all_commands = registry.get_all()
    assert len(all_commands) == 2
    assert all_commands["test1"] == cmd1
    assert all_commands["test2"] == cmd2


@pytest.mark.asyncio
async def test_command_service_process_no_commands():
    """Test processing messages with no commands."""
    # Arrange
    registry = CommandRegistry()
    session_service = MockSessionService()
    service = CommandService(registry, session_service)
    
    # Create a session
    await session_service.get_session("test-session")
    
    # Create messages with no commands
    messages = [
        {"role": "user", "content": "Hello, how are you?"},
        {"role": "assistant", "content": "I'm doing well, how about you?"}
    ]
    
    # Act
    result = await service.process_commands(messages, "test-session")
    
    # Assert
    assert result.modified_messages == messages
    assert result.command_executed is False
    assert len(result.command_results) == 0


@pytest.mark.asyncio
async def test_command_service_process_with_command():
    """Test processing messages with a command."""
    # Arrange
    registry = CommandRegistry()
    session_service = MockSessionService()
    service = CommandService(registry, session_service)
    
    # Create a mock command
    cmd = MockCommand("test")
    registry.register(cmd)
    
    # Create a session
    await session_service.get_session("test-session")
    
    # Create messages with a command
    messages = [
        {"role": "user", "content": "!/test(arg1=value1, arg2=value2) and some text"},
        {"role": "assistant", "content": "I'll process that command."}
    ]
    
    # Act
    result = await service.process_commands(messages, "test-session")
    
    # Assert
    assert cmd.called
    assert cmd.args == {"arg1": "value1", "arg2": "value2"}
    assert result.command_executed is True
    assert len(result.command_results) == 1
    assert result.command_results[0].success is True
    assert result.command_results[0].message == "Command executed"
    assert result.command_results[0].data["name"] == "test"
    
    # The command should be removed from the message
    assert result.modified_messages[0]["content"] == " and some text"


@pytest.mark.asyncio
async def test_command_service_unknown_command():
    """Test processing messages with an unknown command."""
    # Arrange
    registry = CommandRegistry()
    session_service = MockSessionService()
    service = CommandService(registry, session_service, preserve_unknown=True)
    
    # Create a session
    await session_service.get_session("test-session")
    
    # Create messages with an unknown command
    messages = [
        {"role": "user", "content": "!/unknown(arg=value) and some text"},
        {"role": "assistant", "content": "I don't know that command."}
    ]
    
    # Act
    result = await service.process_commands(messages, "test-session")
    
    # Assert
    assert result.command_executed is False
    assert len(result.command_results) == 0
    
    # The unknown command should be preserved
    assert result.modified_messages[0]["content"] == "!/unknown(arg=value) and some text"
    
    # Test with preserve_unknown=False
    service = CommandService(registry, session_service, preserve_unknown=False)
    result = await service.process_commands(messages, "test-session")
    
    # The unknown command should be removed
    assert result.modified_messages[0]["content"] == " and some text"


@pytest.mark.asyncio
async def test_command_service_register_command():
    """Test registering a command."""
    # Arrange
    registry = CommandRegistry()
    session_service = MockSessionService()
    service = CommandService(registry, session_service)
    
    # Act
    cmd = MockCommand("new-command")
    await service.register_command("new-command", cmd)
    
    # Assert
    assert registry.get("new-command") == cmd
