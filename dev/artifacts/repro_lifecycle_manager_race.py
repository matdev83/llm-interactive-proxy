"""Repro script for race condition in BackendLifecycleManager._shutdown_tasks."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


async def create_shutdown_tasks_concurrently():
    """Simulate concurrent additions to _shutdown_tasks set."""
    from src.core.services.backend_lifecycle_manager import (
        BackendLifecycleManager,
    )

    manager = BackendLifecycleManager()

    # Create 100 shutdown tasks concurrently
    async def create_and_add_task():
        async def noop():
            await asyncio.sleep(0.01)
            return

        task = asyncio.create_task(noop())
        manager._shutdown_tasks.add(task)
        return task

    tasks = [create_and_add_task() for _ in range(100)]
    created_tasks = await asyncio.gather(*tasks)

    print("Expected 100 tasks in _shutdown_tasks")
    print(f"Actual tasks in _shutdown_tasks: {len(manager._shutdown_tasks)}")

    # Check for missing tasks
    missing = len(created_tasks) - len(manager._shutdown_tasks)
    if missing > 0:
        print(f"RACE CONDITION DETECTED: {missing} tasks missing from set!")
        return False
    else:
        print("No race condition detected")
        return True


if __name__ == "__main__":
    for i in range(10):
        print(f"\n--- Run {i+1} ---")
        success = asyncio.run(create_shutdown_tasks_concurrently())
        if not success:
            print("Failed on first error - exiting")
            break
