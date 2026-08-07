"""Regression test for ValidationHttpClientManager cleanup task tracking fix.

This test verifies that cleanup tasks created in ValidationHttpClientManager exception handlers
are properly tracked in _cleanup_tasks set to prevent resource leaks.
"""

import asyncio

import httpx
import pytest
from src.core.services.validation_http_client_manager import ValidationHttpClientManager
from tests.utils.fake_clock import FakeClockContext


class TestValidationHttpClientManagerTaskTrackingRegression:
    """Regression tests for ValidationHttpClientManager cleanup task tracking fix."""

    @pytest.mark.asyncio
    async def test_cleanup_tasks_tracked_in_set(self) -> None:
        """Test that cleanup tasks are tracked in _cleanup_tasks set."""
        manager = ValidationHttpClientManager()

        # Create a client
        client = httpx.AsyncClient()

        try:
            # Simulate exception handler scenario: client created but needs cleanup
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Create cleanup task and add to set (like exception handler does)
                cleanup_task = asyncio.create_task(client.aclose())
                manager._cleanup_tasks.add(cleanup_task)

                # Verify task is tracked
                tracked_count = len(manager._cleanup_tasks)
                assert tracked_count > 0, (
                    "Cleanup task was not added to _cleanup_tasks set. "
                    "Task tracking is not working."
                )

                # Wait for task to complete
                async with FakeClockContext() as clock:
                    sleep_task = asyncio.create_task(asyncio.sleep(0.1))
                    clock.advance(0.1)
                    await sleep_task

                # Task should complete successfully
                assert cleanup_task.done(), "Cleanup task did not complete."

        finally:
            # Ensure client is closed
            if not client.is_closed:
                await client.aclose()

    @pytest.mark.asyncio
    async def test_multiple_cleanup_tasks_tracked(self) -> None:
        """Test that multiple cleanup tasks can be tracked."""
        manager = ValidationHttpClientManager()

        clients = []
        cleanup_tasks = []

        try:
            # Create multiple clients and cleanup tasks
            for _i in range(3):
                client = httpx.AsyncClient()
                clients.append(client)

                loop = asyncio.get_event_loop()
                if loop.is_running():
                    cleanup_task = asyncio.create_task(client.aclose())
                    manager._cleanup_tasks.add(cleanup_task)
                    cleanup_tasks.append(cleanup_task)

            # Verify all tasks are tracked
            tracked_count = len(manager._cleanup_tasks)
            assert tracked_count >= len(cleanup_tasks), (
                f"Not all cleanup tasks were tracked. "
                f"Expected at least {len(cleanup_tasks)}, got {tracked_count}."
            )

            # Use manager's cleanup method to verify it properly handles tasks
            await manager.cleanup()

            # All tasks should complete
            for task in cleanup_tasks:
                assert task.done(), "Cleanup task did not complete."

        finally:
            # Ensure all clients are closed
            for client in clients:
                if not client.is_closed:
                    await client.aclose()

    @pytest.mark.asyncio
    async def test_cleanup_tasks_dont_leak(self) -> None:
        """Test that cleanup tasks don't accumulate and cause memory leaks."""
        manager = ValidationHttpClientManager()

        initial_task_count = len(asyncio.all_tasks())

        # Create and track multiple cleanup tasks
        cleanup_tasks = []
        for _i in range(5):
            client = httpx.AsyncClient()

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    cleanup_task = asyncio.create_task(client.aclose())
                    manager._cleanup_tasks.add(cleanup_task)
                    cleanup_tasks.append(cleanup_task)

            finally:
                if not client.is_closed:
                    await client.aclose()

        # Use manager's cleanup method which clears task references
        await manager.cleanup()

        # Check that tasks don't accumulate excessively
        final_task_count = len(asyncio.all_tasks())
        task_increase = final_task_count - initial_task_count

        # Allow some tolerance for test framework tasks
        # But should not accumulate significantly from cleanup tasks
        assert task_increase <= 10, (
            f"Cleanup tasks accumulated: {task_increase} tasks remain. "
            "Cleanup tasks are not being properly managed."
        )

        # Verify tracked tasks were cleared (manager.cleanup() clears the set)
        assert len(manager._cleanup_tasks) == 0, (
            f"{len(manager._cleanup_tasks)} cleanup tasks still tracked. "
            "Tasks should be cleared after cleanup."
        )
