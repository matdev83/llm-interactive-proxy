"""
Reproduction script for memory leak in PromptHandler._active_requests

This script simulates the actual code path to verify if completed tasks
are properly cleaned up.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from unittest.mock import Mock, AsyncMock, patch
from codebuff.handlers.prompt_handler import PromptHandler, _MAX_ACTIVE_REQUESTS


class MockConnection:
    """Mock WebSocket connection."""
    pass


async def test_actual_code_path():
    """Test the actual code path through _stream_response_with_tracking."""

    backend_factory = Mock()
    backend_factory._config = Mock()
    backend_factory._config.backends = {"openai": Mock()}
    backend_factory.ensure_backend = AsyncMock(return_value=Mock())

    format_converter = Mock()
    format_converter.codebuff_to_openai = Mock(return_value=[])
    format_converter.create_response_chunk = AsyncMock()
    format_converter.create_prompt_response = AsyncMock()
    format_converter.create_error_response = Mock()

    connection_manager = Mock()
    connection_manager.get_session = Mock(return_value=None)

    handler = PromptHandler(
        backend_factory=backend_factory,
        format_converter=format_converter,
        connection_manager=connection_manager,
    )

    websocket = MockConnection()
    num_iterations = 150

    print(f"Testing actual code path with {num_iterations} requests...")
    print(f"(Each request should auto-cleanup via task's finally block)")
    print()

    # Simulate multiple requests
    for i in range(num_iterations):
        from codebuff.schemas import PromptAction
        action = PromptAction(
            type="prompt",
            promptId=f"prompt_{i}",
            prompt=f"test prompt {i}",
            fingerprintId="test-fingerprint",
            sessionState={},
        )

        try:
            # This should create a task that cleans itself up on completion
            await handler.handle_prompt(websocket, action)
        except:
            # Errors are expected since we're using mocks
            pass

        # Small delay to let task complete
        await asyncio.sleep(0.01)

    # Wait a bit more for any pending cleanup
    await asyncio.sleep(0.1)

    # Check how many entries remain
    print(f"\nAfter {num_iterations} requests:")
    print(f"  _active_requests size: {len(handler._active_requests)}")

    # Count completed vs active
    completed_count = 0
    active_count = 0
    for prompt_id, task in handler._active_requests.items():
        if task.done():
            completed_count += 1
        else:
            active_count += 1

    print(f"  Completed (done) tasks: {completed_count}")
    print(f"  Active (not done) tasks: {active_count}")
    print(f"  Total entries: {len(handler._active_requests)}")

    if completed_count > 0:
        print("\n[!] POTENTIAL ISSUE: Completed tasks still present")
        print(f"    {completed_count} completed tasks remain in _active_requests")
        print("    These should have been cleaned up by task's finally block")
        return False
    else:
        print("\n[OK] No completed tasks in _active_requests")
        return True


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Memory Leak Test for PromptHandler._active_requests")
    print("=" * 60)
    print()

    result = await test_actual_code_path()

    print("\n" + "=" * 60)
    if not result:
        print("CONCLUSION: Memory leak detected!")
        print("Completed tasks are accumulating in _active_requests")
    else:
        print("CONCLUSION: No memory leak detected")
        print("Tasks are being cleaned up properly")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
