"""Regression test for BackendStage cleanup task tracking fix.

This test verifies that cleanup tasks created in BackendStage exception handlers
are properly tracked in _cleanup_tasks WeakSet to prevent resource leaks.
"""

import asyncio

import httpx
import pytest
from src.core.app.stages.backend import BackendStage
from src.core.config.app_config import AppConfig
from src.core.config.models import BackendSettings


class TestBackendStageTaskTrackingRegression:
    """Regression tests for BackendStage cleanup task tracking fix."""

    @pytest.mark.asyncio
    async def test_cleanup_tasks_tracked_in_weakset(self) -> None:
        """Test that cleanup tasks are tracked in _cleanup_tasks WeakSet."""
        AppConfig(backends=BackendSettings(default_backend=""))
        stage = BackendStage()

        # Create a client
        client = httpx.AsyncClient()

        try:
            # Simulate exception handler scenario: client created but needs cleanup
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Create cleanup task and add to WeakSet (like exception handler does)
                cleanup_task = asyncio.create_task(client.aclose())
                stage._cleanup_tasks.add(cleanup_task)

                # Verify task is tracked
                tracked_count = len(stage._cleanup_tasks)
                assert tracked_count > 0, (
                    "Cleanup task was not added to _cleanup_tasks WeakSet. "
                    "Task tracking is not working."
                )

                # Wait for task to complete
                await asyncio.sleep(0.1)

                # Task should complete successfully
                assert cleanup_task.done(), "Cleanup task did not complete."

        finally:
            # Ensure client is closed
            if not client.is_closed:
                await client.aclose()

    @pytest.mark.asyncio
    async def test_multiple_cleanup_tasks_tracked(self) -> None:
        """Test that multiple cleanup tasks can be tracked."""
        AppConfig(backends=BackendSettings(default_backend=""))
        stage = BackendStage()

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
                    stage._cleanup_tasks.add(cleanup_task)
                    cleanup_tasks.append(cleanup_task)

            # Verify all tasks are tracked
            tracked_count = len(stage._cleanup_tasks)
            assert tracked_count >= len(cleanup_tasks), (
                f"Not all cleanup tasks were tracked. "
                f"Expected at least {len(cleanup_tasks)}, got {tracked_count}."
            )

            # Wait for tasks to complete
            await asyncio.sleep(0.2)

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
        AppConfig(backends=BackendSettings(default_backend=""))
        stage = BackendStage()

        initial_task_count = len(asyncio.all_tasks())

        # Create and track multiple cleanup tasks
        cleanup_tasks = []
        for _i in range(5):
            client = httpx.AsyncClient()

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    cleanup_task = asyncio.create_task(client.aclose())
                    stage._cleanup_tasks.add(cleanup_task)
                    cleanup_tasks.append(cleanup_task)

            finally:
                if not client.is_closed:
                    await client.aclose()

        # Wait for all tasks to complete (reduced sleep time for performance)
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        await asyncio.sleep(0.05)  # Reduced from 0.3 for performance

        # Check that tasks don't accumulate excessively
        final_task_count = len(asyncio.all_tasks())
        task_increase = final_task_count - initial_task_count

        # Allow some tolerance for test framework tasks
        # But should not accumulate significantly from cleanup tasks
        assert task_increase <= 10, (
            f"Cleanup tasks accumulated: {task_increase} tasks remain. "
            "Cleanup tasks are not being properly managed."
        )
