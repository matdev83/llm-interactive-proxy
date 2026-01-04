"""
Repro script for race condition in ICMPHealthChecker.

The global _ping_executor is accessed without proper synchronization
across multiple threads.
"""

import threading
from concurrent.futures import ThreadPoolExecutor


class PingExecutor:
    """Simulates the problematic code from icmp_checker.py."""

    def __init__(self):
        self._ping_executor = None

    def _get_ping_executor(self):
        """Get or create shared thread pool for ping operations - RACE CONDITION."""
        if self._ping_executor is None:
            # Race condition: Multiple threads can enter this block simultaneously
            self._ping_executor = ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="ping_check"
            )
        return self._ping_executor


def simulate_race():
    """Simulate concurrent access to trigger race condition."""
    executor_mgr = PingExecutor()
    results = []

    def access_executor():
        executor = executor_mgr._get_ping_executor()
        results.append(id(executor))

    # Create multiple threads that try to get executor simultaneously
    threads = []
    for _ in range(10):
        t = threading.Thread(target=access_executor)
        threads.append(t)
        t.start()

    # Start all threads at once
    for t in threads:
        t.join()

    # Check if all threads got to same executor
    unique_executors = set(results)
    if len(unique_executors) > 1:
        print(
            f"RACE CONDITION DETECTED: {len(unique_executors)} different executors created"
        )
        return True
    elif len(results) == 10:
        print("No race condition detected in this run")
        return False
    else:
        print(f"Unexpected result: {len(results)} threads completed")
        return False


if __name__ == "__main__":
    print("Running race condition test for ICMPHealthChecker...")
    print("-" * 60)

    # Run multiple iterations to increase chance of detecting race
    race_detected = False
    for i in range(5):
        print(f"\nIteration {i + 1}:")
        if simulate_race():
            race_detected = True

    print("-" * 60)
    if race_detected:
        print("RESULT: Race condition CONFIRMED")
    else:
        print("RESULT: Race condition may exist but not detected (non-deterministic)")
    print("\nFix: Add a threading.Lock() to protect _ping_executor initialization")
