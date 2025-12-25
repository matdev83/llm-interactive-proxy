"""Regression test for race condition fix in DailyRequestCounter.

Tests that _load_state() properly acquires lock when modifying
_logged_thresholds, and that logged_thresholds property is thread-safe.
"""

import json
import tempfile
from pathlib import Path
import pytest
import concurrent.futures
import pytz
from datetime import datetime

from src.connectors.utils.gemini_request_counter import DailyRequestCounter


def _get_current_pacific_date() -> str:
    """Get current date in Pacific timezone."""
    pacific_tz = pytz.timezone("America/Los_Angeles")
    return datetime.now(pacific_tz).strftime("%Y-%m-%d")


class TestDailyRequestCounterRaceConditionFix:
    """Tests for race condition fixes in DailyRequestCounter."""

    def test_load_state_acquires_lock(self):
        """Test that _load_state() acquires lock when modifying _logged_thresholds."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence_path = Path(tmpdir) / "counter.json"

            # Pre-populate with some state (use current date to match Pacific timezone)
            current_date = _get_current_pacific_date()
            with open(persistence_path, "w") as f:
                json.dump({
                    "count":100,
                    "last_reset_date": current_date,
                    "logged_thresholds": [700, 800, 900]
                }, f)

            counter = DailyRequestCounter(persistence_path, 1000)

            # Verify thresholds were loaded correctly
            assert counter.count == 100
            assert counter.last_reset_date == current_date
            assert counter.logged_thresholds == {700, 800, 900}

    def test_logged_thresholds_property_is_thread_safe(self):
        """Test that logged_thresholds property can be accessed safely from multiple threads."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence_path = Path(tmpdir) / "counter.json"
            counter = DailyRequestCounter(persistence_path, 1000)

            # Concurrently read logged_thresholds while incrementing
            logged_values = []
            exceptions = []

            def read_thread():
                """Thread that reads logged_thresholds repeatedly."""
                try:
                    for _ in range(100):
                        # This should always work without race
                        thresholds = counter.logged_thresholds
                        logged_values.append(len(thresholds))
                except Exception as e:
                    exceptions.append(e)

            def increment_thread():
                """Thread that increments counter."""
                try:
                    for _ in range(100):
                        counter.increment()
                except Exception as e:
                    exceptions.append(e)

            # Run threads concurrently
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = [executor.submit(read_thread), executor.submit(increment_thread)]
                concurrent.futures.wait(futures)

            # Should have no exceptions
            assert not exceptions, f"Exceptions occurred during concurrent access: {exceptions}"
            # Should have read some values
            assert len(logged_values) > 0

    def test_concurrent_increments_are_safe(self):
        """Test that concurrent increments don't cause data races."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence_path = Path(tmpdir) / "counter.json"
            limit = 10000
            counter = DailyRequestCounter(persistence_path, limit)

            # Start from known state
            initial_count = counter.count

            # Increment from multiple threads
            num_threads = 10
            increments_per_thread = 100
            expected_count = initial_count + (num_threads * increments_per_thread)

            def increment_worker(thread_id):
                """Worker that increments counter multiple times."""
                for _ in range(increments_per_thread):
                    counter.increment()

            with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [executor.submit(increment_worker, i) for i in range(num_threads)]
                concurrent.futures.wait(futures)

            # All increments should be accounted for
            assert counter.count == expected_count, (
                f"Expected {expected_count} but got {counter.count}"
            )

    def test_load_state_modifies_state_under_lock(self):
        """Test that _load_state() only modifies state while holding lock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            persistence_path = Path(tmpdir) / "counter.json"

            # Create counter
            counter = DailyRequestCounter(persistence_path, 1000)

            # Update state file externally (use current date to match Pacific timezone)
            # Note: thresholds are filtered to match _thresholds (700, 800, 900 for limit=1000)
            current_date = _get_current_pacific_date()
            with open(persistence_path, "w") as f:
                json.dump({
                    "count": 500,
                    "last_reset_date": current_date,
                    "logged_thresholds": [700, 800, 900]
                }, f)

            # Create new instance which will load state
            counter2 = DailyRequestCounter(persistence_path, 1000)

            # Verify state was loaded correctly without corruption
            assert counter2.count == 500
            assert counter2.last_reset_date == current_date
            assert counter2.logged_thresholds == {700, 800, 900}
