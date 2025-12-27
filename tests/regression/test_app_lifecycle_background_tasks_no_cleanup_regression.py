"""Regression test for AppLifecycle background tasks leak when cleanup is disabled.

This test verifies that AppLifecycle._background_tasks don't grow unbounded
when session_cleanup_enabled is False and cleanup is never called.
"""

import asyncio

import pytest
from fastapi import FastAPI
from src.core.app.lifecycle import AppLifecycle
from tests.utils.fake_clock import FakeClockContext


class TestAppLifecycleBackgroundTasksNoCleanupRegression:
    """Regression tests for AppLifecycle background tasks when cleanup is disabled."""

    @pytest.mark.asyncio
    async def test_background_tasks_accumulate_when_cleanup_disabled(self) -> None:
        """Test that background tasks accumulate when cleanup is disabled."""
        app = FastAPI()
        config = {"session_cleanup_enabled": False}
        lifecycle = AppLifecycle(app, config)

        initial_count = len(lifecycle._background_tasks)

        # Create many tasks without cleanup
        num_tasks = 100
        for i in range(num_tasks):

            async def dummy_task(task_id: int = i):
                async with FakeClockContext() as clock:
                    sleep_task = asyncio.create_task(asyncio.sleep(0.001))
                    clock.advance(0.001)
                    await sleep_task
                return task_id

            task = asyncio.create_task(dummy_task())
            lifecycle._background_tasks.append(task)
            task.add_done_callback(lifecycle._remove_completed_task)

        # Wait for all tasks to complete (reduced from 0.5s to 0.05s)
        async with FakeClockContext() as clock:
            for _ in range(10):
                sleep_task = asyncio.create_task(asyncio.sleep(0.01))
                clock.advance(0.01)
                await sleep_task

        # Without cleanup, tasks should still be removed by callbacks
        # But if callbacks aren't working, tasks accumulate
        final_count = len(lifecycle._background_tasks)

        # Tasks should be cleaned up by callbacks even without explicit cleanup
        # The callback (_remove_completed_task) should handle this
        assert final_count <= initial_count + 10, (
            f"Background tasks accumulated when cleanup disabled. "
            f"Initial: {initial_count}, Final: {final_count}, Expected: ~{initial_count}. "
            f"{final_count - initial_count} completed tasks accumulated."
        )

    @pytest.mark.asyncio
    async def test_manual_cleanup_works_when_enabled(self) -> None:
        """Test that manual cleanup works even when session_cleanup_enabled is False."""
        app = FastAPI()
        config = {"session_cleanup_enabled": False}
        lifecycle = AppLifecycle(app, config)

        initial_count = len(lifecycle._background_tasks)

        # Create many tasks
        num_tasks = 100
        for i in range(num_tasks):

            async def dummy_task(task_id: int = i):
                async with FakeClockContext() as clock:
                    sleep_task = asyncio.create_task(asyncio.sleep(0.001))
                    clock.advance(0.001)
                    await sleep_task
                return task_id

            task = asyncio.create_task(dummy_task())
            lifecycle._background_tasks.append(task)
            task.add_done_callback(lifecycle._remove_completed_task)

        # Wait for tasks to complete (reduced from 0.5s to 0.05s)
        async with FakeClockContext() as clock:
            for _ in range(10):
                sleep_task = asyncio.create_task(asyncio.sleep(0.01))
                clock.advance(0.01)
                await sleep_task

        # Manually call cleanup
        lifecycle._cleanup_completed_tasks()

        final_count = len(lifecycle._background_tasks)

        # Manual cleanup should work regardless of session_cleanup_enabled setting
        assert final_count <= initial_count + 10, (
            f"Manual cleanup didn't work. "
            f"Initial: {initial_count}, Final: {final_count}, Expected: ~{initial_count}."
        )
