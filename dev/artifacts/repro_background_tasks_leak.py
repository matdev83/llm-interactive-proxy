"""
Repro script to confirm memory leak in ResponseProcessor._background_tasks.

The issue: Background tasks are appended to a list but never removed,
even after they complete. This causes unbounded memory growth.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.streaming.stream_normalizer import StreamNormalizer


async def create_and_complete_task(task_id: int) -> asyncio.Task:
    """Create a simple background task that completes quickly."""

    async def dummy_task():
        await asyncio.sleep(0.01)  # Very short task
        return f"task_{task_id}"

    return asyncio.create_task(dummy_task())


async def main():
    """Demonstrate unbounded growth of _background_tasks list."""
    print("Creating ResponseProcessor instance...")

    # Create minimal mocks for required dependencies
    mock_parser = MagicMock()
    mock_stream_normalizer = MagicMock(spec=StreamNormalizer)

    # Create ResponseProcessor with minimal dependencies
    processor = ResponseProcessor(  # noqa: DI-bypass - Dev artifact repro script needs direct instantiation
        response_parser=mock_parser,
        app_state=None,
        stream_normalizer=mock_stream_normalizer,
    )

    print(f"Initial _background_tasks size: {len(processor._background_tasks)}")

    # Add many tasks that complete quickly
    num_tasks = 1000
    print(f"\nAdding {num_tasks} background tasks...")

    for i in range(num_tasks):
        task = await create_and_complete_task(i)
        processor.add_background_task(task)

        # Wait a bit for tasks to complete
        if i % 100 == 0:
            await asyncio.sleep(0.1)
            completed = sum(1 for t in processor._background_tasks if t.done())
            print(
                f"  Added {i+1} tasks, {completed} completed, "
                f"list size: {len(processor._background_tasks)}"
            )

    # Wait for all tasks to complete
    print("\nWaiting for all tasks to complete...")
    await asyncio.sleep(2)

    # Check final state
    completed_count = sum(1 for t in processor._background_tasks if t.done())
    print("\nFinal state:")
    print(f"  Total tasks in list: {len(processor._background_tasks)}")
    print(f"  Completed tasks: {completed_count}")
    print(f"  Pending tasks: {len(processor._background_tasks) - completed_count}")

    # Check if leak is fixed: tasks should be removed when they complete
    if len(processor._background_tasks) == 0:
        print("\n[FIXED] Memory leak resolved!")
        print("  - All completed tasks were automatically removed")
        print("  - List size is 0 (all tasks completed and cleaned up)")
        return True
    elif len(processor._background_tasks) < num_tasks:
        print("\n[PARTIAL] Some cleanup occurred")
        print(f"  - {len(processor._background_tasks)} tasks remain out of {num_tasks}")
        print(f"  - {completed_count} tasks completed")
        # Check if remaining tasks are pending
        pending = sum(1 for t in processor._background_tasks if not t.done())
        if pending > 0:
            print(f"  - {pending} tasks still pending (expected)")
        return True
    else:
        print("\n[LEAK CONFIRMED] Memory leak still present!")
        print("  - All tasks completed but remain in _background_tasks list")
        print("  - List grows unbounded without cleanup")
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
