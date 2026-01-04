"""Reproduction script for race condition in DailyRequestCounter.

This script demonstrates that _load_state() modifies _logged_thresholds
without acquiring the lock, causing potential race conditions when multiple
threads access the counter.
"""

import concurrent.futures
import json
import tempfile
from pathlib import Path

from src.connectors.utils.gemini_request_counter import DailyRequestCounter


def test_race_condition_in_load_state():
    """Test race condition when _load_state() and increment() run concurrently."""
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence_path = Path(tmpdir) / "counter.json"
        limit = 1000

        # Pre-populate with some state
        with open(persistence_path, "w") as f:
            json.dump(
                {
                    "count": 100,
                    "last_reset_date": "2025-01-01",
                    "logged_thresholds": [700, 800, 900],
                },
                f,
            )

        counter = DailyRequestCounter(persistence_path, limit)

        # Simulate concurrent access: increment from multiple threads while _load_state() could be called
        errors = []
        results = []

        def increment_thread(thread_id):
            """Thread that increments counter."""
            try:
                for i in range(100):
                    counter.increment()
                results.append(f"Thread {thread_id} completed successfully")
            except Exception as e:
                errors.append(f"Thread {thread_id} error: {e}")

        # Start multiple increment threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(increment_thread, i) for i in range(10)]
            concurrent.futures.wait(futures)

        if errors:
            print("RACE CONDITION DETECTED:")
            for error in errors:
                print(f"  {error}")
            return False
        else:
            print("No errors detected (but race condition still exists)")
            print(f"Final count: {counter.count}")
            print(f"Logged thresholds: {counter.logged_thresholds}")
            return True


def test_unsafe_logged_thresholds_access():
    """Test that logged_thresholds property is not thread-safe."""
    with tempfile.TemporaryDirectory() as tmpdir:
        persistence_path = Path(tmpdir) / "counter.json"
        counter = DailyRequestCounter(persistence_path, 1000)

        # Concurrently read logged_thresholds while incrementing
        errors = []
        logged_values = []

        def read_thread():
            """Thread that reads logged_thresholds."""
            try:
                for _ in range(1000):
                    # This creates a copy, but without lock protection
                    thresholds = counter.logged_thresholds
                    logged_values.append(len(thresholds))
            except Exception as e:
                errors.append(f"Read thread error: {e}")

        def increment_thread():
            """Thread that increments counter."""
            try:
                for _ in range(1000):
                    counter.increment()
            except Exception as e:
                errors.append(f"Increment thread error: {e}")

        with concurrent.futures.ThreadPoolExecutor() as executor:
            futures = [executor.submit(read_thread), executor.submit(increment_thread)]
            concurrent.futures.wait(futures)

        if errors:
            print("UNSAFE ACCESS DETECTED:")
            for error in errors:
                print(f"  {error}")
            return False
        else:
            print("Logged thresholds access seems safe")
            return True


if __name__ == "__main__":
    print("=" * 60)
    print("Test 1: Race condition in _load_state()")
    print("=" * 60)
    test_race_condition_in_load_state()

    print("\n" + "=" * 60)
    print("Test 2: Unsafe logged_thresholds property access")
    print("=" * 60)
    test_unsafe_logged_thresholds_access()
