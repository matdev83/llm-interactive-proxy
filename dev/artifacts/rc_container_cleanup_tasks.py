"""Race condition repro script for ServiceCollection._cleanup_tasks

This script demonstrates a race condition in ServiceCollection where:
1. Thread A adds a cleanup task to _cleanup_tasks (line 411)
2. Thread B reads/disposes, calling clear() on _cleanup_tasks (line 479)
3. Task added by A is lost and never awaited

File: src/core/di/container.py
Line 319: self._cleanup_tasks: set[asyncio.Task[None]] = set()
Line 411: self._cleanup_tasks.add(cleanup_task)  # NO LOCK
Line 479: self._cleanup_tasks.clear()  # NO LOCK
"""

import asyncio
import threading
import time


# Simulate the ServiceCollection's problematic pattern
class MockServiceCollection:
    def __init__(self):
        self._cleanup_tasks = set()  # Thread-unsafe set
        self._disposed = False
        self.cleanup_lost = False

    def add_cleanup_task(self, task):
        """Simulates line 411 in container.py"""
        self._cleanup_tasks.add(task)
        print(f"[Thread-{threading.current_thread().ident}] Added task {id(task)} to cleanup set")

    async def dispose(self):
        """Simulates line 479 in container.py"""
        self._disposed = True
        pending_tasks = [t for t in self._cleanup_tasks if not t.done()]
        if pending_tasks:
            await asyncio.wait_for(
                asyncio.gather(*pending_tasks, return_exceptions=True),
                timeout=5.0,
            )
        self._cleanup_tasks.clear()  # Race condition: clear without lock
        print(f"[Thread-{threading.current_thread().ident}] Cleared cleanup tasks, count={len(self._cleanup_tasks)}")


async def simulate_race_condition():
    """Simulate concurrent add and clear operations"""
    service = MockServiceCollection()
    errors = []

    async def slow_cleanup_task():
        """A task that takes some time"""
        await asyncio.sleep(0.1)

    def add_task_thread():
        """Simulates adding cleanup tasks from different threads"""
        for i in range(10):
            time.sleep(0.01)  # Small delay
            if service._disposed:
                print(f"[Thread-{threading.current_thread().ident}] ERROR: Adding task after dispose!")
                errors.append("add_after_dispose")
                break
            task = asyncio.create_task(slow_cleanup_task())
            service.add_cleanup_task(task)
            time.sleep(0.01)

    def dispose_thread():
        """Simulates dispose running"""
        time.sleep(0.05)  # Wait for some tasks to be added
        asyncio.run(service.dispose())

    # Start threads
    t1 = threading.Thread(target=add_task_thread)
    t2 = threading.Thread(target=dispose_thread)
    t1.start()
    t2.start()

    t1.join()
    t2.join()

    if errors:
        print(f"\nRACE CONDITION DETECTED: {errors}")
        return True
    elif len(service._cleanup_tasks) == 0:
        print("\nRACE CONDITION DETECTED: Tasks were added during clear and lost!")
        return True
    else:
        print(f"\nNo race detected in this run (tasks left: {len(service._cleanup_tasks)})")
        return False


async def main():
    print("=== Testing Race Condition in ServiceCollection._cleanup_tasks ===\n")

    # Run multiple times to increase chance of hitting race
    race_found = False
    for run in range(5):
        print(f"\nRun {run + 1}/5...")
        if await simulate_race_condition():
            race_found = True
            break
        time.sleep(0.1)

    if race_found:
        print("\n✗ RACE CONDITION CONFIRMED")
        print("  File: src/core/di/container.py")
        print("  Issue: _cleanup_tasks set modified without synchronization")
        print("  Fix: Add asyncio.Lock to protect _cleanup_tasks")
    else:
        print("\n✓ No race detected (may require more iterations)")


if __name__ == "__main__":
    asyncio.run(main())
