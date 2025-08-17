"""Debug test for session state persistence."""

import asyncio
import logging

from src.core.commands.handler_factory import register_command_handlers
from src.core.repositories.in_memory_session_repository import InMemorySessionRepository
from src.core.services.command_service import CommandRegistry, CommandService
from src.core.services.session_service import SessionService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_session_persistence():
    """Test session state persistence through command execution."""

    # Setup services
    repo = InMemorySessionRepository()
    session_service = SessionService(repo)
    command_registry = CommandRegistry()
    register_command_handlers(command_registry)
    command_service = CommandService(command_registry, session_service, False)

    # Create initial session
    session_id = "test-session"
    session = await session_service.get_session(session_id)

    print(f"Initial session state - project: {session.state.project}")

    # Process a set command
    messages = [{"role": "user", "content": "!/set(project=test-project)"}]

    result = await command_service.process_commands(messages, session_id)

    print(f"Command executed: {result.command_executed}")
    if result.command_results:
        print(f"Command result: {result.command_results[0].message}")

    # Get the session again to check if state was persisted
    session_after = await session_service.get_session(session_id)

    print(f"Session state after command - project: {session_after.state.project}")

    # Check repository directly
    session_from_repo = await repo.get_by_id(session_id)
    if session_from_repo:
        print(f"Session from repo - project: {session_from_repo.state.project}")

    assert (
        session_after.state.project == "test-project"
    ), f"Expected project to be 'test-project', got {session_after.state.project}"
    print("✓ Test passed!")


if __name__ == "__main__":
    asyncio.run(test_session_persistence())
