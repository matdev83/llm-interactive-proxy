"""Regression test for race condition in DailyRequestCounter lock creation.

This test ensures that _lock is created early enough to protect
state during initialization and concurrent access.

GitHub Issue: DailyRequestCounter lock creation order race condition
File: src/connectors/utils/gemini_request_counter.py
"""

import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from src.connectors.utils.gemini_request_counter import DailyRequestCounter


class TestDailyRequestCounterLockOrder:
    """Tests for proper lock creation order in DailyRequestCounter."""

    def test_lock_exists_immediately_after_init(self):
        """Test that _lock exists immediately after initialization."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(
                '{"count": 0, "last_reset_date": "2025-01-01", "logged_thresholds": []}'
            )
            temp_path = Path(f.name)

        try:
            counter = DailyRequestCounter(temp_path, limit=100)

            # Lock should exist immediately
            assert hasattr(counter, "_lock"), "_lock should exist after initialization"
            assert counter._lock is not None, "_lock should not be None"

            # Lock should be usable
            with counter._lock:
                pass  # Should not raise
        finally:
            temp_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_concurrent_increments_with_threading(self):
        """Test that concurrent increments are properly protected."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(
                '{"count": 0, "last_reset_date": "2025-01-01", "logged_thresholds": []}'
            )
            temp_path = Path(f.name)

        try:
            counter = DailyRequestCounter(temp_path, limit=1000)

            # Perform concurrent increments
            num_threads = 50
            increments_per_thread = 10

            def increment_many():
                for _ in range(increments_per_thread):
                    counter.increment()

            with ThreadPoolExecutor(max_workers=num_threads) as executor:
                futures = [executor.submit(increment_many) for _ in range(num_threads)]
                for future in futures:
                    future.result()  # Wait for completion

            # All increments should be counted
            expected_count = num_threads * increments_per_thread
            assert (
                counter.count == expected_count
            ), f"Expected {expected_count} increments, got {counter.count}"
        finally:
            temp_path.unlink(missing_ok=True)

    def test_increment_protects_shared_state(self):
        """Test that increment() properly protects shared state."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(
                '{"count": 0, "last_reset_date": "2025-01-01", "logged_thresholds": []}'
            )
            temp_path = Path(f.name)

        try:
            counter = DailyRequestCounter(temp_path, limit=100)

            # Save initial state
            initial_count = counter.count
            initial_date = counter.last_reset_date

            # Increment multiple times
            for _ in range(10):
                counter.increment()

            # State should be consistent
            assert counter.count == initial_count + 10
            assert counter.last_reset_date == initial_date

            # Check persistence
            with open(temp_path, encoding="utf-8") as f:
                data = json.load(f)
                assert data["count"] == counter.count
                assert data["last_reset_date"] == counter.last_reset_date
        finally:
            temp_path.unlink(missing_ok=True)

    def test_load_state_protected_after_init(self):
        """Test that _load_state is safe to call after initialization."""
        from datetime import datetime

        import pytz

        # Get current Pacific date to avoid reset
        pacific_tz = pytz.timezone("America/Los_Angeles")
        current_date = datetime.now(pacific_tz).strftime("%Y-%m-%d")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            initial_data = {
                "count": 42,
                "last_reset_date": current_date,
                "logged_thresholds": [70, 80],
            }
            json.dump(initial_data, f)
            temp_path = Path(f.name)

        try:
            counter = DailyRequestCounter(temp_path, limit=100)

            # State should be loaded correctly
            assert counter.count == 42
            assert counter.last_reset_date == current_date
            assert 70 in counter.logged_thresholds
            assert 80 in counter.logged_thresholds

            # Increment should work correctly after loading
            counter.increment()
            assert counter.count == 43
        finally:
            temp_path.unlink(missing_ok=True)

    def test_load_state_with_corrupted_file(self):
        """Test that _load_state handles corrupted JSON gracefully."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"count": "not a number", "last_reset_date": "2025-01-01"}')
            temp_path = Path(f.name)

        try:
            # Should not crash, will use defaults
            counter = DailyRequestCounter(temp_path, limit=100)

            # Should have default values
            assert counter.count == 0  # Failed to load, uses default
            assert hasattr(counter, "_lock")
        finally:
            temp_path.unlink(missing_ok=True)

    def test_save_state_protected(self):
        """Test that _save_state works correctly with persistence."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(
                '{"count": 0, "last_reset_date": "2025-01-01", "logged_thresholds": []}'
            )
            temp_path = Path(f.name)

        try:
            counter = DailyRequestCounter(temp_path, limit=100)

            # Increment to trigger save
            counter.increment()

            # Verify state was saved
            with open(temp_path, encoding="utf-8") as f:
                data = json.load(f)

            assert data["count"] == 1
            assert "last_reset_date" in data
            assert "logged_thresholds" in data
        finally:
            temp_path.unlink(missing_ok=True)

    def test_reset_if_needed_updates_state(self):
        """Test that _reset_if_needed correctly updates state."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            # Set old date to trigger reset
            f.write(
                '{"count": 99, "last_reset_date": "2024-12-31", "logged_thresholds": [70, 80]}'
            )
            temp_path = Path(f.name)

        try:
            counter = DailyRequestCounter(temp_path, limit=100)

            # Should have been reset
            assert counter.count == 0, "Count should be reset to 0"
            assert (
                len(counter.logged_thresholds) == 0
            ), "Logged thresholds should be cleared"

            # Verify persistence
            with open(temp_path, encoding="utf-8") as f:
                data = json.load(f)

            assert data["count"] == 0
            assert data["logged_thresholds"] == []
        finally:
            temp_path.unlink(missing_ok=True)

    def test_lock_reusability(self):
        """Test that the same lock instance is reused for all operations."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(
                '{"count": 0, "last_reset_date": "2025-01-01", "logged_thresholds": []}'
            )
            temp_path = Path(f.name)

        try:
            counter = DailyRequestCounter(temp_path, limit=100)

            # Store lock reference
            lock_ref = counter._lock

            # Perform various operations
            counter.increment()
            counter.increment()

            # Lock should be the same instance
            assert counter._lock is lock_ref, "Lock instance should be reused"
        finally:
            temp_path.unlink(missing_ok=True)

    def test_threshold_logging_with_lock(self):
        """Test that threshold logging works correctly with lock protection."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(
                '{"count": 0, "last_reset_date": "2025-01-01", "logged_thresholds": []}'
            )
            temp_path = Path(f.name)

        try:
            # Set low limit for testing
            counter = DailyRequestCounter(temp_path, limit=10)

            # Increment past thresholds (70%, 80%, 90% of 10 = 7, 8, 9)
            for _i in range(10):
                counter.increment()

            # All thresholds should have been logged
            assert 7 in counter.logged_thresholds, "70% threshold should be logged"
            assert 8 in counter.logged_thresholds, "80% threshold should be logged"
            assert 9 in counter.logged_thresholds, "90% threshold should be logged"
        finally:
            temp_path.unlink(missing_ok=True)
