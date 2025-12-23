"""Regression test for InMemoryUsageStore persistence thread leak fix.

This test verifies that InMemoryUsageStore properly stops the persistence thread
when stop_persistence_thread() is called, preventing thread leaks when the
store is destroyed without explicit cleanup.

Fixed: stop_persistence_thread() properly signals shutdown and joins the thread.
"""

import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from src.core.services.in_memory_usage_store import InMemoryUsageStore


class TestInMemoryUsageStoreThreadLeakRegression:
    """Regression tests for InMemoryUsageStore thread leak fix."""

    @pytest.fixture
    def temp_dir(self) -> Path:
        """Create a temporary directory for persistence files."""
        with TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_stop_persistence_thread_cleans_up_thread(self, temp_dir: Path) -> None:
        """Test that stop_persistence_thread() properly stops the thread."""
        store = InMemoryUsageStore(
            persistence_path=temp_dir / "test_usage_store.json",
            flush_interval_seconds=1.0,
        )

        # Count threads before
        threads_before = threading.active_count()

        # Start persistence thread
        store.start_persistence_thread()

        # Wait a bit to ensure thread started
        time.sleep(0.2)

        # Verify thread is running
        assert store._flush_thread is not None, "Persistence thread should exist"
        assert store._flush_thread.is_alive(), "Persistence thread should be alive"

        threads_after_start = threading.active_count()
        assert (
            threads_after_start > threads_before
        ), "Persistence thread should increase thread count"

        # Stop persistence thread
        store.stop_persistence_thread()

        # Wait for thread to stop
        time.sleep(0.3)

        # Verify thread is stopped
        assert (
            store._flush_thread is None or not store._flush_thread.is_alive()
        ), "Persistence thread should be stopped"

        threads_after_stop = threading.active_count()
        # Allow some margin for other threads
        assert threads_after_stop <= threads_before + 2, (
            f"Thread count should return to near baseline. "
            f"Before: {threads_before}, After: {threads_after_stop}"
        )

    def test_multiple_instances_with_stop(self, temp_dir: Path) -> None:
        """Test that multiple instances can be stopped without leaking threads."""
        threads_before = threading.active_count()

        stores = []
        for i in range(3):
            store = InMemoryUsageStore(
                persistence_path=temp_dir / f"test_usage_store_{i}.json",
                flush_interval_seconds=1.0,
            )
            store.start_persistence_thread()
            stores.append(store)
            time.sleep(0.1)

        threads_after_creation = threading.active_count()
        assert (
            threads_after_creation > threads_before
        ), "Multiple persistence threads should increase thread count"

        # Stop all threads
        for store in stores:
            store.stop_persistence_thread()

        # Wait for threads to stop
        time.sleep(0.5)

        # Verify all threads are stopped
        running_threads = sum(
            1
            for store in stores
            if store._flush_thread is not None and store._flush_thread.is_alive()
        )
        assert (
            running_threads == 0
        ), f"All persistence threads should be stopped. Found {running_threads} running"

        threads_after_stop = threading.active_count()
        # Allow margin for other threads
        assert threads_after_stop <= threads_before + 5, (
            f"Thread count should return to near baseline. "
            f"Before: {threads_before}, After: {threads_after_stop}"
        )

    def test_rapid_start_stop_cycle(self, temp_dir: Path) -> None:
        """Test rapid start/stop cycles don't leak threads."""
        threads_before = threading.active_count()

        # Rapidly create, start, and stop stores
        for i in range(10):
            store = InMemoryUsageStore(
                persistence_path=temp_dir / f"test_usage_store_{i}.json",
                flush_interval_seconds=0.5,
            )
            store.start_persistence_thread()
            time.sleep(0.05)  # Small delay to let thread start
            store.stop_persistence_thread()
            time.sleep(0.05)  # Small delay to let thread stop

        # Wait for all threads to stop
        time.sleep(0.5)

        threads_after = threading.active_count()
        # Allow margin for other threads
        assert threads_after <= threads_before + 5, (
            f"Rapid cycles should not leak threads. "
            f"Before: {threads_before}, After: {threads_after}"
        )

    def test_double_stop_is_safe(self, temp_dir: Path) -> None:
        """Test that calling stop_persistence_thread() twice is safe."""
        store = InMemoryUsageStore(
            persistence_path=temp_dir / "test_usage_store.json",
            flush_interval_seconds=1.0,
        )

        store.start_persistence_thread()
        time.sleep(0.1)

        # Stop first time
        store.stop_persistence_thread()
        time.sleep(0.1)

        # Stop second time (should be safe)
        store.stop_persistence_thread()

        # Should not raise exception
        assert (
            store._flush_thread is None or not store._flush_thread.is_alive()
        ), "Thread should be stopped"

    def test_stop_without_start_is_safe(self, temp_dir: Path) -> None:
        """Test that calling stop_persistence_thread() without start is safe."""
        store = InMemoryUsageStore(
            persistence_path=temp_dir / "test_usage_store.json",
            flush_interval_seconds=1.0,
        )

        # Stop without starting (should be safe)
        store.stop_persistence_thread()

        # Should not raise exception
        assert (
            store._flush_thread is None or not store._flush_thread.is_alive()
        ), "Thread should not exist"
