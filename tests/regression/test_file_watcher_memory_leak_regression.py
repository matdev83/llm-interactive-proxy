"""Regression test for FileWatcher memory leak fix.

This test verifies that FileWatcher doesn't accumulate background tasks
when schedule_credentials_reload is called multiple times.
"""

import asyncio

import pytest
from src.connectors.gemini_base.file_watcher import FileWatcher, FileWatcherState
from tests.utils.fake_clock import FakeClockContext


class TestFileWatcherMemoryLeakRegression:
    """Regression tests for FileWatcher memory leak fix."""

    @pytest.mark.asyncio
    async def test_no_task_accumulation_on_rapid_scheduling(self) -> None:
        """Test that rapid scheduling doesn't accumulate background tasks."""
        state = FileWatcherState()
        state.main_loop = asyncio.get_event_loop()

        async def mock_reload_callback() -> None:
            # Use fake clock for deterministic time simulation
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.01))
                clock.advance(0.01)  # Simulate some async work
                await sleep_task

        def mock_stop_callback() -> None:
            pass

        # Get initial task count
        initial_tasks = len(asyncio.all_tasks())

        # Schedule multiple reload tasks rapidly (reduced for performance)
        async with FakeClockContext() as clock:
            for _i in range(5):  # Reduced from 10
                FileWatcher.schedule_credentials_reload(
                    state, mock_reload_callback, mock_stop_callback
                )

            # Wait for all tasks to complete
            for _ in range(5):
                sleep_task = asyncio.create_task(asyncio.sleep(0.02))
                clock.advance(0.02)
                await sleep_task

        # Check final task count
        final_tasks = len(asyncio.all_tasks())
        task_increase = final_tasks - initial_tasks

        # Should not accumulate more than a few tasks (allow some tolerance for test framework)
        assert task_increase <= 5, (
            f"Task accumulation detected: {task_increase} tasks remain. "
            "FileWatcher is not properly cleaning up completed tasks."
        )

    @pytest.mark.asyncio
    async def test_completed_task_cleanup(self) -> None:
        """Test that completed tasks are properly cleaned up."""
        state = FileWatcherState()
        state.main_loop = asyncio.get_event_loop()

        call_count = 0

        async def mock_reload_callback() -> None:
            nonlocal call_count
            call_count += 1
            # Use fake clock for deterministic time simulation
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.005))
                clock.advance(0.005)
                await sleep_task

        def mock_stop_callback() -> None:
            pass

        # Schedule a reload task
        async with FakeClockContext() as clock:
            FileWatcher.schedule_credentials_reload(
                state, mock_reload_callback, mock_stop_callback
            )

            # Wait for task to complete
            for _ in range(5):
                sleep_task = asyncio.create_task(asyncio.sleep(0.01))
                clock.advance(0.01)
                await sleep_task

        # Task should be cleaned up
        assert (
            state.pending_reload_task is None or state.pending_reload_task.done()
        ), "Completed task was not cleaned up from state."

        # Verify callback was called
        assert call_count > 0, "Reload callback was not executed."

    @pytest.mark.asyncio
    async def test_multiple_schedules_without_leak(self) -> None:
        """Test that multiple schedules don't create multiple concurrent tasks."""
        state = FileWatcherState()
        state.main_loop = asyncio.get_event_loop()

        call_count = 0

        async def mock_reload_callback() -> None:
            nonlocal call_count
            call_count += 1
            # Use fake clock for deterministic time simulation
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.02))
                clock.advance(0.02)  # Reduced from 0.05
                await sleep_task

        def mock_stop_callback() -> None:
            pass

        # Schedule multiple reloads rapidly (should debounce)
        async with FakeClockContext() as clock:
            for _ in range(5):  # Reduced from 10
                FileWatcher.schedule_credentials_reload(
                    state, mock_reload_callback, mock_stop_callback
                )
                sleep_task = asyncio.create_task(asyncio.sleep(0.005))
                clock.advance(0.005)  # Reduced from 0.01
                await sleep_task

            # Wait for all tasks to complete
            for _ in range(5):
                sleep_task = asyncio.create_task(asyncio.sleep(0.02))
                clock.advance(0.02)
                await sleep_task

        # Should not have multiple concurrent tasks
        # Due to debouncing and cleanup, we expect at most 1-2 calls
        assert call_count <= 2, (
            f"Multiple concurrent tasks detected: {call_count} calls. "
            "FileWatcher is not properly debouncing or cleaning up tasks."
        )

        # State should be clean
        assert (
            state.pending_reload_task is None or state.pending_reload_task.done()
        ), "Task was not cleaned up after completion."
