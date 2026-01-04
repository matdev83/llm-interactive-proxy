"""Repro script for race condition in ServiceCollection._cleanup_tasks."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def add_cleanup_tasks_concurrently():
    """Simulate concurrent additions to _cleanup_tasks set in ServiceCollection."""
    from src.core.di.container import ServiceCollection

    collection = ServiceCollection()

    # Create 100 cleanup tasks concurrently
    async def create_and_add_task():
        async def noop():
            await asyncio.sleep(0.01)
            return

        task = asyncio.create_task(noop())
        collection._cleanup_tasks.add(task)
        return task

    tasks = [create_and_add_task() for _ in range(100)]
    created_tasks = await asyncio.gather(*tasks)

    print("Expected 100 tasks in _cleanup_tasks")
    print(f"Actual tasks in _cleanup_tasks: {len(collection._cleanup_tasks)}")

    # Check for missing tasks
    missing = len(created_tasks) - len(collection._cleanup_tasks)
    if missing > 0:
        print(f"RACE CONDITION DETECTED: {missing} tasks missing from set!")
        return False
    else:
        print("No race condition detected")
        return True


if __name__ == "__main__":
    for i in range(10):
        print(f"\n--- Run {i+1} ---")
        success = asyncio.run(add_cleanup_tasks_concurrently())
        if not success:
            print("Failed on first error - exiting")
            break
