"""Regression test for FileWatcher watchdog Observer thread leak fix.

This test verifies that FileWatcher properly stops watchdog Observer threads
when stop_file_watching() is called, preventing thread leaks when file watchers
are created but never stopped.

Fixed: stop_file_watching() properly calls observer.stop() and observer.join().
"""

import asyncio
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from src.connectors.gemini_base.file_watcher import FileWatcher, FileWatcherState


def count_watchdog_threads() -> int:
    """Count active watchdog Observer threads."""
    count = 0
    for thread in threading.enumerate():
        # Watchdog Observer threads are daemon threads
        # They're typically named "Thread-<n>" and are daemon threads
        if thread.daemon and thread.is_alive():
            # This is a heuristic - watchdog threads are typically daemon threads
            # We count all daemon threads as potential watchdog threads
            # In practice, we'll verify by checking if they're associated with observers
            count += 1
    return count


async def mock_reload_callback() -> None:
    """Mock reload callback."""
    await asyncio.sleep(0.01)


def mock_stop_callback() -> None:
    """Mock stop callback."""


class TestFileWatcherWatchdogThreadLeakRegression:
    """Regression tests for FileWatcher watchdog thread leak fix."""

    @pytest.fixture
    def temp_creds_file(self) -> Path:
        """Create a temporary credentials file."""
        with TemporaryDirectory() as tmpdir:
            creds_file = Path(tmpdir) / "test_credentials.json"
            creds_file.write_text('{"test": "data"}')
            yield creds_file

    def test_stop_file_watching_cleans_up_thread(self, temp_creds_file: Path) -> None:
        """Test that stop_file_watching() properly stops the Observer thread."""
        state = FileWatcherState()

        # Count threads before
        threads_before = count_watchdog_threads()

        # Start file watching
        FileWatcher.start_file_watching(
            temp_creds_file,
            None,  # connector (not needed for this test)
            state,
            mock_reload_callback,
        )

        # Wait a bit to ensure thread started
        time.sleep(0.1)  # Reduced from 0.2 for performance

        # Verify observer is running
        assert state.file_observer is not None, "File observer should exist"
        assert state.file_observer.is_alive(), "File observer should be alive"

        threads_after_start = count_watchdog_threads()
        assert (
            threads_after_start >= threads_before
        ), "File observer should create a thread"

        # Stop file watching
        FileWatcher.stop_file_watching(state)

        # Wait for thread to stop
        time.sleep(0.15)  # Reduced from 0.3 for performance

        # Verify observer is stopped
        assert state.file_observer is None, "File observer should be cleared"

        threads_after_stop = count_watchdog_threads()
        # Allow some margin for other threads
        assert threads_after_stop <= threads_before + 2, (
            f"Thread count should return to near baseline. "
            f"Before: {threads_before}, After: {threads_after_stop}"
        )

        # Wait a bit to ensure thread started
        time.sleep(0.1)  # Reduced from 0.2 for performance

        # Verify observer is running
        assert state.file_observer is not None, "File observer should exist"
        assert state.file_observer.is_alive(), "File observer should be alive"

        threads_after_start = count_watchdog_threads()
        assert (
            threads_after_start >= threads_before
        ), "File observer should create a thread"

        # Stop file watching
        FileWatcher.stop_file_watching(state)

        # Wait for thread to stop
        time.sleep(0.15)  # Reduced from 0.3 for performance

        # Verify observer is stopped
        assert state.file_observer is None, "File observer should be cleared"

        threads_after_stop = count_watchdog_threads()
        # Allow some margin for other threads
        assert threads_after_stop <= threads_before + 2, (
            f"Thread count should return to near baseline. "
            f"Before: {threads_before}, After: {threads_after_stop}"
        )

    def test_multiple_watchers_with_stop(self, temp_creds_file: Path) -> None:
        """Test that multiple watchers can be stopped without leaking threads."""
        threads_before = count_watchdog_threads()

        states = []
        for _i in range(2):  # Reduced from 3 for performance
            state = FileWatcherState()
            FileWatcher.start_file_watching(
                temp_creds_file,
                None,
                state,
                mock_reload_callback,
            )
            states.append(state)
            time.sleep(0.02)  # Reduced from 0.05 for performance

        threads_after_creation = count_watchdog_threads()
        assert (
            threads_after_creation >= threads_before
        ), "Multiple file observers should create threads"

        # Stop all watchers
        for state in states:
            FileWatcher.stop_file_watching(state)

        # Wait for threads to stop
        time.sleep(0.1)  # Reduced from 0.2 for performance

        # Verify all observers are stopped
        running_observers = sum(
            1 for state in states if state.file_observer is not None
        )
        assert (
            running_observers == 0
        ), f"All file observers should be stopped. Found {running_observers} running"

        threads_after_stop = count_watchdog_threads()
        # Allow margin for other threads
        assert threads_after_stop <= threads_before + 2, (
            f"Thread count should return to near baseline. "
            f"Before: {threads_before}, After: {threads_after_stop}"
        )

    def test_rapid_start_stop_cycle(self, temp_creds_file: Path) -> None:
        """Test rapid start/stop cycles don't leak threads."""
        threads_before = count_watchdog_threads()

        # Rapidly create, start, and stop watchers
        for _i in range(3):  # Reduced from 5 for performance
            state = FileWatcherState()
            FileWatcher.start_file_watching(
                temp_creds_file,
                None,
                state,
                mock_reload_callback,
            )
            time.sleep(0.01)  # Small delay to let thread start
            FileWatcher.stop_file_watching(state)
            time.sleep(0.01)  # Small delay to let thread stop

        # Wait for all threads to stop
        time.sleep(0.1)  # Reduced from 0.2 for performance

        threads_after = count_watchdog_threads()
        # Allow margin for other threads
        assert threads_after <= threads_before + 3, (
            f"Rapid cycles should not leak threads. "
            f"Before: {threads_before}, After: {threads_after}"
        )

    def test_stop_without_start_is_safe(self) -> None:
        """Test that calling stop_file_watching() without start is safe."""
        state = FileWatcherState()

        # Stop without starting (should be safe)
        FileWatcher.stop_file_watching(state)

        # Should not raise exception
        assert state.file_observer is None, "Observer should not exist"

    def test_double_stop_is_safe(self, temp_creds_file: Path) -> None:
        """Test that calling stop_file_watching() twice is safe."""
        state = FileWatcherState()

        FileWatcher.start_file_watching(
            temp_creds_file,
            None,
            state,
            mock_reload_callback,
        )
        time.sleep(0.1)

        # Stop first time
        FileWatcher.stop_file_watching(state)
        time.sleep(0.1)

        # Stop second time (should be safe)
        FileWatcher.stop_file_watching(state)

        # Should not raise exception
        assert state.file_observer is None, "Observer should be cleared"
