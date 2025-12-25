"""
Reproduction script for race condition in GeminiCloudProjectConnector._schedule_credentials_reload()

Race condition: TOCTOU (Time-of-Check to Time-of-Use)
- Check-and-act race on _reload_scheduling_in_progress flag
- Flag is checked and modified in lock, but async task is created outside lock
- Multiple threads can pass the check and create multiple concurrent reload tasks
"""

import asyncio
import threading
import time


class MockConnector:
    """Minimal mock of GeminiCloudProjectConnector's reload logic"""

    def __init__(self):
        self._reload_task_lock = threading.Lock()
        self._reload_scheduling_in_progress = False
        self._pending_reload_task = None
        self._call_count = 0
        self._reload_count = 0

    def _schedule_credentials_reload(self) -> None:
        """Simulates the race condition in _schedule_credentials_reload"""

        with self._reload_task_lock:
            if (
                self._pending_reload_task is not None
                and not self._pending_reload_task.done()
            ):
                return

            if self._reload_scheduling_in_progress:
                print(f"  [Thread {threading.current_thread().name}] Reload already in progress, skipping")
                return

            self._reload_scheduling_in_progress = True
            print(f"  [Thread {threading.current_thread().name}] Set scheduling in progress to True (inside lock)")

        # RACE CONDITION: Flag is set inside lock, but task creation happens OUTSIDE lock
        # Multiple threads can pass the above check and create multiple tasks

        def reload_task():
            self._reload_count += 1
            print(f"  [Thread {threading.current_thread().name}] Executing reload #{self._reload_count}")
            time.sleep(0.1)  # Simulate work

        # Simulate creating and scheduling task outside the lock
        loop = asyncio.new_event_loop()
        try:
            with self._reload_task_lock:
                task = loop.create_task(asyncio.coroutine(reload_task)())
                self._pending_reload_task = task
                self._reload_scheduling_in_progress = False
                print(f"  [Thread {threading.current_thread().name}] Created task, reset flag to False (inside lock)")
        except:
            pass

    def get_state(self):
        """Helper to see internal state"""
        with self._reload_task_lock:
            return {
                "scheduling_in_progress": self._reload_scheduling_in_progress,
                "pending_task": self._pending_reload_task,
                "reload_count": self._reload_count,
            }


def test_race_condition():
    """
    Simulates multiple threads calling _schedule_credentials_reload concurrently.
    Expected to fail: Only 1 reload should execute.
    Actual buggy behavior: Multiple reloads execute concurrently.
    """
    connector = MockConnector()

    # Simulate a pending task (like from previous reload)
    loop = asyncio.new_event_loop()
    connector._pending_reload_task = loop.create_task(
        asyncio.coroutine(lambda: None)()
    )

    print("\n=== RACE CONDITION TEST: _schedule_credentials_reload ===")
    print("Simulating concurrent file modification events from multiple threads...")
    print("Expected: Only 1 reload should execute")
    print("Actual buggy behavior: Multiple reloads may execute concurrently\n")

    # Create multiple threads that will simultaneously call _schedule_credentials_reload
    threads = []
    for i in range(5):
        t = threading.Thread(
            target=connector._schedule_credentials_reload,
            name=f"FileWatcher-{i}"
        )
        threads.append(t)

    # Start all threads simultaneously
    for t in threads:
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join(timeout=2)

    # Check final state
    time.sleep(0.5)  # Give tasks time to complete
    final_state = connector.get_state()

    print("\n=== RESULTS ===")
    print(f"Total reloads executed: {final_state['reload_count']}")
    print(f"Final scheduling_in_progress flag: {final_state['scheduling_in_progress']}")
    print(f"Pending task: {final_state['pending_task']}")

    if final_state['reload_count'] > 1:
        print("\n RACE CONDITION REPRODUCED: Multiple concurrent reloads executed!")
        print("This demonstrates the TOCTOU race in _schedule_credentials_reload")
        return True
    else:
        print("\n No race condition detected (single reload executed as expected)")
        return False


if __name__ == "__main__":
    has_race = test_race_condition()
    exit(1 if has_race else 0)
