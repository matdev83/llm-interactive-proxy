"""Race condition repro for gemini_cloud_project.py

This script demonstrates the race condition in _schedule_credentials_reload
where multiple file modifications can cause inconsistent state.
"""
import asyncio
import threading
import time


class MockConnector:
    """Mock connector simulating the race condition."""

    def __init__(self):
        self._pending_reload_task = None
        self._reload_task_lock = threading.Lock()
        self._reload_scheduling_in_progress = False

    def _schedule_credentials_reload(self):
        """
        Simulates the race condition in _schedule_credentials_reload.

        The problem: _reload_scheduling_in_progress is checked and modified
        without being protected by the same lock.
        """
        # This check is NOT protected by _reload_task_lock
        if self._reload_scheduling_in_progress:
            print("Skipped reload: _reload_scheduling_in_progress already set")
            return

        # Set flag WITHOUT acquiring lock
        self._reload_scheduling_in_progress = True

        # Simulate the gap between setting flag and acquiring lock
        time.sleep(0.001)  # 1ms window

        # Now acquire lock
        with self._reload_task_lock:
            # Another thread might have already set _reload_scheduling_in_progress
            # while we were waiting for the lock
            print(f"Scheduled reload: _pending_reload_task={self._pending_reload_task}")

            # Simulate scheduling completion
            def clear_callback(_):
                self._pending_reload_task = None
                self._reload_scheduling_in_progress = False

            self._pending_reload_task = "fake_task"
            self._pending_reload_task.add_done_callback(clear_callback)


def simulate_concurrent_modifications():
    """Simulate concurrent file modifications."""
    connector = MockConnector()

    async def modification_event():
        """Simulate a file modification event from multiple threads."""
        connector._schedule_credentials_reload()

    # Schedule 10 concurrent modifications
    tasks = [modification_event() for _ in range(10)]
    await asyncio.gather(*tasks)

    # Allow all callbacks to complete
    await asyncio.sleep(0.1)

    # Check for inconsistencies
    if connector._reload_scheduling_in_progress:
        print("RACE CONDITION DETECTED: _reload_scheduling_in_progress still True!")
        return False

    if connector._pending_reload_task is not None:
        print("RACE CONDITION DETECTED: _pending_reload_task not cleared!")
        return False

    print("No race condition detected")
    return True


if __name__ == "__main__":
    success = asyncio.run(simulate_concurrent_modifications())
    if not success:
        print("FAILED: Race conditions found!")
        exit(1)
    else:
        print("PASSED")
        exit(0)
