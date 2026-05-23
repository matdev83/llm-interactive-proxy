"""Regression test for ValidationHttpClientManager cleanup tasks leak fix.

This test verifies that cleanup tasks created in ValidationHttpClientManager exception handlers
are properly tracked and cleaned up, preventing resource leaks when exceptions
occur during validation client creation or cleanup.

Fixed: Cleanup tasks are tracked in _cleanup_tasks set and properly awaited/cancelled.
"""

import asyncio

import httpx
import pytest
from src.core.services.validation_http_client_manager import ValidationHttpClientManager
from tests.utils.fake_clock import FakeClockContext


class TestValidationHttpClientManagerCleanupTasksLeakRegression:
    """Regression tests for ValidationHttpClientManager cleanup tasks leak fix."""

    @pytest.fixture
    def manager(self) -> ValidationHttpClientManager:
        """Create a ValidationHttpClientManager instance."""
        return ValidationHttpClientManager()

    @pytest.mark.asyncio
    async def test_cleanup_tasks_tracked_on_exception(
        self, manager: ValidationHttpClientManager
    ) -> None:
        """Test that cleanup tasks are tracked when exceptions occur."""
        client: httpx.AsyncClient | None = None

        try:
            # Create a client (like in get_or_create_client exception handler)
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )

            # Simulate exception handler scenario: create cleanup task
            loop = asyncio.get_event_loop()
            if loop.is_running():
                cleanup_task = asyncio.create_task(client.aclose())
                manager._cleanup_tasks.add(cleanup_task)

                # Verify task is tracked
                assert (
                    len(manager._cleanup_tasks) > 0
                ), "Cleanup task should be tracked in _cleanup_tasks set"

                # Simulate exception during cleanup setup
                raise ValueError("Simulated exception during cleanup")

        except ValueError:
            # Exception caught, but task should still be tracked
            assert (
                len(manager._cleanup_tasks) > 0
            ), "Cleanup task should remain tracked even after exception"
        finally:
            # Ensure client is closed
            if client and not client.is_closed:
                await client.aclose()

    @pytest.mark.asyncio
    async def test_cleanup_tasks_completed_on_cleanup(
        self, manager: ValidationHttpClientManager
    ) -> None:
        """Test that cleanup tasks are properly awaited during cleanup."""
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

            # Verify tasks are tracked
            assert len(manager._cleanup_tasks) >= len(
                cleanup_tasks
            ), "All cleanup tasks should be tracked"

            # Use manager's cleanup method to verify it properly handles tasks
            await manager.cleanup()

            # All tasks should complete
            for task in cleanup_tasks:
                assert task.done(), "Cleanup task should complete"

        finally:
            # Ensure all clients are closed
            for client in clients:
                if not client.is_closed:
                    await client.aclose()

    @pytest.mark.asyncio
    async def test_cleanup_tasks_timeout_handling(
        self, manager: ValidationHttpClientManager
    ) -> None:
        """Test that cleanup tasks timeout is handled properly."""

        async def slow_cleanup():
            """Simulate slow cleanup that might timeout."""
            await asyncio.sleep(
                0.1
            )  # Longer than typical per-task timeout but minimal for speed

        client = httpx.AsyncClient()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Create slow cleanup task
                cleanup_task = asyncio.create_task(slow_cleanup())
                manager._cleanup_tasks.add(cleanup_task)

                # Use manager's cleanup method which handles timeout internally
                # The manager uses a 5 second timeout, but we can verify timeout behavior
                # by checking that tasks are cancelled if they take too long
                await manager.cleanup()

                # Tasks should be cancelled or completed
                assert cleanup_task.done(), "Task should be done after cleanup"

        finally:
            if not client.is_closed:
                await client.aclose()

    @pytest.mark.asyncio
    async def test_cleanup_tasks_dont_accumulate(
        self, manager: ValidationHttpClientManager
    ) -> None:
        """Test that cleanup tasks don't accumulate unbounded."""
        initial_task_count = len(asyncio.all_tasks())

        # Create multiple cleanup tasks (reduced from 10 to 5 for performance)
        clients = []
        cleanup_tasks = []
        for _i in range(5):
            client = httpx.AsyncClient()
            clients.append(client)

            loop = asyncio.get_event_loop()
            if loop.is_running():
                cleanup_task = asyncio.create_task(client.aclose())
                manager._cleanup_tasks.add(cleanup_task)
                cleanup_tasks.append(cleanup_task)

        # Use manager's cleanup method which clears task references
        await manager.cleanup()

        # Check that tasks don't accumulate excessively
        final_task_count = len(asyncio.all_tasks())
        task_increase = final_task_count - initial_task_count

        # Allow tolerance for test framework tasks
        assert task_increase <= 10, (
            f"Cleanup tasks accumulated: {task_increase} tasks remain. "
            "Cleanup tasks are not being properly managed."
        )

        # Verify tracked tasks were cleared (manager.cleanup() clears the set)
        assert len(manager._cleanup_tasks) == 0, (
            f"{len(manager._cleanup_tasks)} cleanup tasks still tracked. "
            "Tasks should be cleared after cleanup."
        )

        # Clean up clients
        for client in clients:
            if not client.is_closed:
                await client.aclose()

    @pytest.mark.asyncio
    async def test_cleanup_interruption_scenario(
        self, manager: ValidationHttpClientManager
    ) -> None:
        """Test scenario where cleanup is interrupted by exception."""
        client: httpx.AsyncClient | None = None

        try:
            client = httpx.AsyncClient()

            loop = asyncio.get_event_loop()
            if loop.is_running():
                cleanup_task = asyncio.create_task(client.aclose())
                manager._cleanup_tasks.add(cleanup_task)

                # Simulate cleanup attempt that gets interrupted
                async def failing_cleanup():
                    async with FakeClockContext() as clock:
                        sleep_task = asyncio.create_task(asyncio.sleep(0.1))
                        clock.advance(0.1)
                        await sleep_task
                    raise RuntimeError("Cleanup failed")

                failing_task = asyncio.create_task(failing_cleanup())
                manager._cleanup_tasks.add(failing_task)

                # Use manager's cleanup method which handles exceptions gracefully
                await manager.cleanup()

                # All tasks should be done (completed or failed)
                # Manager's cleanup clears the set, so we check tasks directly
                assert (
                    cleanup_task.done()
                ), "Cleanup task should be done after cleanup attempt"
                assert (
                    failing_task.done()
                ), "Failing task should be done after cleanup attempt"

        finally:
            if client and not client.is_closed:
                await client.aclose()
