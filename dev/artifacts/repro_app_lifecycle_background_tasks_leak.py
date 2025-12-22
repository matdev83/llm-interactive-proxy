"""Repro script for AppLifecycle._background_tasks memory leak.

This script demonstrates that completed background tasks accumulate in
the _background_tasks list without being cleaned up, causing unbounded
memory growth.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.app.lifecycle import AppLifecycle
from fastapi import FastAPI


async def main():
    """Demonstrate the memory leak."""
    app = FastAPI()
    config = {}
    lifecycle = AppLifecycle(app, config)

    print("Creating background tasks that complete immediately...")
    print(f"Initial task count: {len(lifecycle._background_tasks)}")

    # Create many tasks that complete immediately
    for i in range(100):
        async def quick_task(task_id: int):
            await asyncio.sleep(0.001)  # Complete quickly
            return task_id

        task = asyncio.create_task(quick_task(i))
        # Use the proper method if available, otherwise test direct access
        if hasattr(lifecycle, '_start_background_tasks'):
            # Simulate how tasks are actually added in the codebase
            lifecycle._cleanup_completed_tasks()
            lifecycle._background_tasks.append(task)
            task.add_done_callback(lifecycle._remove_completed_task)
        else:
            lifecycle._background_tasks.append(task)
        # Wait for task to complete
        await task

    # Wait a bit to ensure all callbacks have fired
    await asyncio.sleep(0.2)

    # Check how many tasks are in the list
    completed_count = sum(1 for t in lifecycle._background_tasks if t.done())
    total_count = len(lifecycle._background_tasks)

    print(f"\nAfter creating 100 tasks:")
    print(f"  Total tasks in list: {total_count}")
    print(f"  Completed tasks: {completed_count}")
    print(f"  Still running: {total_count - completed_count}")

    if total_count == 100 and completed_count == 100:
        print("\n[MEMORY LEAK CONFIRMED] All 100 completed tasks are still in the list!")
        print("   They should have been removed when they completed.")
        return 1
    else:
        print("\n[OK] No leak detected (unexpected)")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
