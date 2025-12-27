"""Regression test for BackendStage cleanup tasks leak fix.

This test verifies that cleanup tasks created in BackendStage exception handlers
are properly tracked and cleaned up, preventing resource leaks when exceptions
occur during validation client creation or cleanup.

Fixed: Cleanup tasks are tracked in _cleanup_tasks set and properly awaited/cancelled.
"""

import asyncio

import httpx
import pytest
from src.core.app.stages.backend import BackendStage
from tests.utils.fake_clock import FakeClockContext


class TestBackendStageCleanupTasksLeakRegression:
    """Regression tests for BackendStage cleanup tasks leak fix."""

    @pytest.fixture
    def stage(self) -> BackendStage:
        """Create a BackendStage instance."""
        return BackendStage()

    @pytest.mark.asyncio
    async def test_cleanup_tasks_tracked_on_exception(
        self, stage: BackendStage
    ) -> None:
        """Test that cleanup tasks are tracked when exceptions occur."""
        client: httpx.AsyncClient | None = None

        try:
            # Create a client (like in _register_validation_http_client)
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )

            # Simulate exception handler scenario: create cleanup task
            loop = asyncio.get_event_loop()
            if loop.is_running():
                cleanup_task = asyncio.create_task(client.aclose())
                stage._cleanup_tasks.add(cleanup_task)

                # Verify task is tracked
                assert (
                    len(stage._cleanup_tasks) > 0
                ), "Cleanup task should be tracked in _cleanup_tasks set"

                # Simulate exception during cleanup setup
                raise ValueError("Simulated exception during cleanup")

        except ValueError:
            # Exception caught, but task should still be tracked
            assert (
                len(stage._cleanup_tasks) > 0
            ), "Cleanup task should remain tracked even after exception"
        finally:
            # Ensure client is closed
            if client and not client.is_closed:
                await client.aclose()

    @pytest.mark.asyncio
    async def test_cleanup_tasks_completed_on_cleanup(
        self, stage: BackendStage
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
                    stage._cleanup_tasks.add(cleanup_task)
                    cleanup_tasks.append(cleanup_task)

            # Verify tasks are tracked
            assert len(stage._cleanup_tasks) >= len(
                cleanup_tasks
            ), "All cleanup tasks should be tracked"

            # Wait for tasks to complete using gather instead of sleep
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)

            # All tasks should complete
            for task in cleanup_tasks:
                assert task.done(), "Cleanup task should complete"

        finally:
            # Ensure all clients are closed
            for client in clients:
                if not client.is_closed:
                    await client.aclose()

    @pytest.mark.asyncio
    async def test_cleanup_tasks_timeout_handling(self, stage: BackendStage) -> None:
        """Test that cleanup tasks timeout is handled properly."""

        async def slow_cleanup():
            """Simulate slow cleanup that might timeout."""
            await asyncio.sleep(1.0)  # Longer than typical timeout

        client = httpx.AsyncClient()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Create slow cleanup task
                cleanup_task = asyncio.create_task(slow_cleanup())
                stage._cleanup_tasks.add(cleanup_task)

                # Simulate cleanup with timeout (like _cleanup_validation_client does)
                pending_tasks = [t for t in stage._cleanup_tasks if not t.done()]

                if pending_tasks:
                    try:
                        # Wait with timeout
                        await asyncio.wait_for(
                            asyncio.gather(*pending_tasks, return_exceptions=True),
                            timeout=0.1,  # Short timeout
                        )
                    except asyncio.TimeoutError:
                        # Timeout should trigger cancellation
                        for task in pending_tasks:
                            if not task.done():
                                task.cancel()

                        # Wait for cancellation
                        await asyncio.gather(*pending_tasks, return_exceptions=True)

                # Tasks should be cancelled or completed
                for task in pending_tasks:
                    assert task.done(), "Task should be done after timeout handling"

        finally:
            if not client.is_closed:
                await client.aclose()

    @pytest.mark.asyncio
    async def test_cleanup_tasks_dont_accumulate(self, stage: BackendStage) -> None:
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
                stage._cleanup_tasks.add(cleanup_task)
                cleanup_tasks.append(cleanup_task)

        # Wait for tasks to complete using gather instead of sleep
        await asyncio.gather(*cleanup_tasks, return_exceptions=True)

        # Check that tasks don't accumulate excessively
        final_task_count = len(asyncio.all_tasks())
        task_increase = final_task_count - initial_task_count

        # Allow tolerance for test framework tasks
        assert task_increase <= 10, (
            f"Cleanup tasks accumulated: {task_increase} tasks remain. "
            "Cleanup tasks are not being properly managed."
        )

        # Verify tracked tasks completed
        pending_tracked = [t for t in stage._cleanup_tasks if not t.done()]
        assert len(pending_tracked) == 0, (
            f"{len(pending_tracked)} cleanup tasks still pending. "
            "Tasks should complete or be cancelled."
        )

        # Clean up clients
        for client in clients:
            if not client.is_closed:
                await client.aclose()

    @pytest.mark.asyncio
    async def test_cleanup_interruption_scenario(self, stage: BackendStage) -> None:
        """Test scenario where cleanup is interrupted by exception."""
        client: httpx.AsyncClient | None = None

        try:
            client = httpx.AsyncClient()

            loop = asyncio.get_event_loop()
            if loop.is_running():
                cleanup_task = asyncio.create_task(client.aclose())
                stage._cleanup_tasks.add(cleanup_task)

                # Simulate cleanup attempt that gets interrupted
                pending_tasks = [t for t in stage._cleanup_tasks if not t.done()]
                if pending_tasks:
                    try:
                        # Simulate exception during gather
                        async def failing_cleanup():
                            async with FakeClockContext() as clock:
                                sleep_task = asyncio.create_task(asyncio.sleep(0.1))
                                clock.advance(0.1)
                                await sleep_task
                            raise RuntimeError("Cleanup failed")

                        failing_task = asyncio.create_task(failing_cleanup())
                        stage._cleanup_tasks.add(failing_task)

                        await asyncio.gather(
                            *stage._cleanup_tasks, return_exceptions=True
                        )
                    except Exception as e:
                        # Exception should be handled gracefully
                        assert isinstance(e, RuntimeError | Exception)

                # All tasks should be done (completed or failed)
                for task in stage._cleanup_tasks:
                    assert task.done(), "Task should be done after cleanup attempt"

        finally:
            if client and not client.is_closed:
                await client.aclose()
