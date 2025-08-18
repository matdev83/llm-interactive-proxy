"""Debug version of the model command test to see what's happening."""

import asyncio
import logging
from unittest.mock import AsyncMock

from src.core.commands.handler_factory import CommandHandlerFactory
from src.core.domain.chat import ChatMessage
from src.core.domain.configuration import (
    BackendConfig,
    LoopDetectionConfig,
    ReasoningConfig,
)
from src.core.domain.session import Session, SessionState
from src.core.services.command_service import CommandRegistry, CommandService

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

def create_command_registry():
    """Create a command registry with registered handlers."""
    registry = CommandRegistry()
    
    # Register handlers using the factory
    factory = CommandHandlerFactory()
    for handler in factory.create_handlers():
        print(f"Registering handler: {handler.name}")
        registry.register(handler)
    return registry

def create_session():
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

def create_session_service(session):
    """Create a mock session service."""
    mock_service = AsyncMock()
    mock_service.get_session = AsyncMock(return_value=session)
    return mock_service

async def debug_test():
    """Debug the model command test."""
    print("Creating command registry...")
    command_registry = create_command_registry()
    
    print("Available commands:", list(command_registry.get_all().keys()))
    
    print("Creating session...")
    session = create_session()
    
    print("Creating session service...")
    session_service = create_session_service(session)
    
    print("Creating command service...")
    command_service = CommandService(command_registry, session_service)
    
    messages = [ChatMessage(role="user", content="!/model(name=gpt-4)")]
    
    print("Processing commands...")
    result = await command_service.process_commands(messages, "test-session")
    
    print("Command executed:", result.command_executed)
    print("Number of command results:", len(result.command_results))
    if result.command_results:
        print("First result success:", result.command_results[0].success)
        print("First result message:", result.command_results[0].message)
        print("First result data:", result.command_results[0].data)
    
    # Verify the result
    assert result.command_executed
    assert len(result.command_results) == 1
    assert result.command_results[0].success
    assert "gpt-4" in result.command_results[0].message
    
    # Verify the message was modified
    assert result.modified_messages[0].content == ""
    
    print("All assertions passed!")

if __name__ == "__main__":
    asyncio.run(debug_test())