"""Regression test for race condition in InfrastructureStage HTTP client cleanup.

This test ensures that HTTP client cleanup tasks are properly tracked and awaited
to prevent resource leaks and unobserved exceptions.

GitHub Issue: InfrastructureStage HTTP client cleanup race condition
File: src/core/app/stages/infrastructure.py
"""

import asyncio
import contextlib
from unittest.mock import patch

import pytest
from src.core.app.stages.infrastructure import InfrastructureStage
from tests.utils.fake_clock import FakeClockContext


class TestInfrastructureStageHttpClientCleanup:
    """Tests for proper HTTP client cleanup task tracking."""

    @pytest.mark.asyncio
    async def test_http_client_cleanup_task_is_tracked_on_failure(self):
        """Test that cleanup tasks are tracked when HTTP client registration fails."""
        stage = InfrastructureStage()

        # Create a simple mock that behaves like httpx.AsyncClient
        class MockHttpxClient:
            def __init__(self):
                self.is_closed = False

            async def aclose(self):
                self.is_closed = True

        mock_client = MockHttpxClient()

        with patch(
            "httpx.AsyncClient",
            side_effect=[mock_client, Exception("Registration failed")],
        ):
            services = type(
                "ServiceCollection",
                (),
                {
                    "build_service_provider": lambda self: type(
                        "Provider", (), {"get_service": lambda self, cls: None}
                    )()
                },
            )()

            from src.core.config.app_config import AppConfig

            config = AppConfig()

            with contextlib.suppress(Exception):
                # Expected to fail due to side_effect
                await stage.execute(services, config)

            # Verify client cleanup was called
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.1))
                clock.advance(0.1)
                await sleep_task
            assert (
                mock_client.is_closed
            ), "HTTP client should be closed on registration failure"

    @pytest.mark.asyncio
    async def test_multiple_cleanup_tasks_are_tracked(self):
        """Test that multiple cleanup tasks are tracked and completed."""
        stage = InfrastructureStage()

        # Wrap entire test in FakeClockContext
        async with FakeClockContext() as clock:
            # Create simple mock clients
            class MockClient:
                def __init__(self, index):
                    self.index = index
                    self.is_closed = False

                async def aclose(self):
                    sleep_task = asyncio.create_task(asyncio.sleep(0.01))
                    clock.advance(0.01)
                    await sleep_task
                    self.is_closed = True

            mock_clients = [MockClient(i) for i in range(3)]

            # Manually simulate cleanup tasks being created
            tasks = []
            for client in mock_clients:
                cleanup_task = asyncio.create_task(client.aclose())
                stage._cleanup_tasks.add(cleanup_task)
                cleanup_task.add_done_callback(stage._cleanup_tasks.discard)
                tasks.append(cleanup_task)

            # Wait for all cleanup tasks to complete explicitly
            await asyncio.gather(*tasks)

            # All clients should be closed
            for client in mock_clients:
                assert client.is_closed, f"Client {client.index} should be closed"

            # Cleanup tasks set should be empty (all tasks completed and removed)
            assert (
                len(stage._cleanup_tasks) == 0
            ), "All cleanup tasks should be completed and removed"

    @pytest.mark.asyncio
    async def test_cleanup_with_failing_tasks(self):
        """Test that exceptions in cleanup tasks don't cause cleanup to hang."""
        stage = InfrastructureStage()

        # Wrap entire test in FakeClockContext
        async with FakeClockContext() as clock:
            # Create clients that fail during cleanup
            class FailingClient:
                def __init__(self, index):
                    self.index = index
                    self.is_closed = False

                async def aclose(self):
                    sleep_task = asyncio.create_task(asyncio.sleep(0.05))
                    clock.advance(0.05)
                    await sleep_task
                    if self.index % 2 == 0:
                        raise Exception(f"Client {self.index} cleanup failed")
                    self.is_closed = True

            failing_clients = [FailingClient(i) for i in range(3)]

            # Create cleanup tasks
            for client in failing_clients:
                cleanup_task = asyncio.create_task(client.aclose())
                stage._cleanup_tasks.add(cleanup_task)
                cleanup_task.add_done_callback(stage._cleanup_tasks.discard)

            # Call cleanup method
            await stage._cleanup_http_client()

            # All tasks should be complete (set should be empty)
            assert len(stage._cleanup_tasks) == 0, "All cleanup tasks should be cleaned up"

            # Verify that some clients closed successfully
            closed_count = sum(1 for client in failing_clients if client.is_closed)
            assert closed_count > 0, "At least some clients should have closed successfully"

    @pytest.mark.asyncio
    async def test_cleanup_timeout_cancels_pending_tasks(self):
        """Test that slow cleanup tasks are cancelled on timeout."""
        stage = InfrastructureStage()

        # Create slow clients that won't finish
        class VerySlowClient:
            def __init__(self, index):
                self.index = index
                self.is_closed = False

            async def aclose(self):
                await asyncio.sleep(10.0)  # Very slow cleanup
                self.is_closed = True

        slow_clients = [VerySlowClient(i) for i in range(2)]

        # Create cleanup tasks
        for client in slow_clients:
            cleanup_task = asyncio.create_task(client.aclose())
            stage._cleanup_tasks.add(cleanup_task)
            cleanup_task.add_done_callback(stage._cleanup_tasks.discard)

        # Patch timeout to be shorter for testing
        original_wait_for = asyncio.wait_for

        async def short_wait_for(coro, timeout):
            # Use very short timeout for testing
            return await original_wait_for(coro, 0.1)

        with patch.object(asyncio, "wait_for", short_wait_for):
            # Call cleanup method - should timeout and cancel
            await stage._cleanup_http_client()

        # Cleanup tasks set should be empty
        assert len(stage._cleanup_tasks) == 0, "All cleanup tasks should be cleaned up"

        # Verify tasks were cancelled (clients not closed due to timeout)
        closed_count = sum(1 for client in slow_clients if client.is_closed)
        assert (
            closed_count == 0
        ), "Clients should not have closed due to timeout/cancellation"

    @pytest.mark.asyncio
    async def test_no_cleanup_tasks_initially(self):
        """Test that cleanup tasks set is empty initially."""
        stage = InfrastructureStage()
        assert len(stage._cleanup_tasks) == 0, "Cleanup tasks should be empty initially"

    @pytest.mark.asyncio
    async def test_cleanup_can_be_called_multiple_times(self):
        """Test that cleanup method can be called multiple times safely."""
        stage = InfrastructureStage()

        # First cleanup with no tasks
        await stage._cleanup_http_client()
        assert len(stage._cleanup_tasks) == 0

        # Add a task and cleanup
        class MockClient:
            def __init__(self):
                self.is_closed = False

            async def aclose(self):
                self.is_closed = True

        mock_client = MockClient()
        cleanup_task = asyncio.create_task(mock_client.aclose())
        stage._cleanup_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(stage._cleanup_tasks.discard)

        async with FakeClockContext() as clock:
            sleep_task = asyncio.create_task(asyncio.sleep(0.1))
            clock.advance(0.1)
            await sleep_task

        await stage._cleanup_http_client()
        assert len(stage._cleanup_tasks) == 0

        # Second cleanup with no tasks should still work
        await stage._cleanup_http_client()
        assert len(stage._cleanup_tasks) == 0

    @pytest.mark.asyncio
    async def test_cleanup_tasks_removed_on_completion(self):
        """Test that completed tasks are removed from tracking set."""
        stage = InfrastructureStage()

        # Create a quick cleanup task
        async def quick_cleanup():
            pass

        task = asyncio.create_task(quick_cleanup())
        stage._cleanup_tasks.add(task)
        task.add_done_callback(stage._cleanup_tasks.discard)

        assert len(stage._cleanup_tasks) == 1

        # Wait for task to complete
        async with FakeClockContext() as clock:
            sleep_task = asyncio.create_task(asyncio.sleep(0.1))
            clock.advance(0.1)
            await sleep_task

        # Task should be removed via callback
        assert len(stage._cleanup_tasks) == 0

    @pytest.mark.asyncio
    async def test_cleanup_handles_task_exceptions(self):
        """Test that exceptions in cleanup tasks don't prevent other tasks from cleaning up."""
        stage = InfrastructureStage()

        # Wrap entire test in FakeClockContext
        async with FakeClockContext() as clock:
            # Create a mix of successful and failing cleanups
            async def failing_cleanup():
                sleep_task = asyncio.create_task(asyncio.sleep(0.01))
                clock.advance(0.01)
                await sleep_task
                raise Exception("Cleanup failed")

            async def successful_cleanup():
                sleep_task = asyncio.create_task(asyncio.sleep(0.01))
                clock.advance(0.01)
                await sleep_task

            # Create tasks
            tasks = [
                asyncio.create_task(failing_cleanup()),
                asyncio.create_task(successful_cleanup()),
                asyncio.create_task(failing_cleanup()),
                asyncio.create_task(successful_cleanup()),
            ]

            for task in tasks:
                stage._cleanup_tasks.add(task)
                task.add_done_callback(stage._cleanup_tasks.discard)

            # Wait a bit then cleanup
            sleep_task = asyncio.create_task(asyncio.sleep(0.1))
            clock.advance(0.1)
            await sleep_task

            # Cleanup should handle exceptions gracefully
            await stage._cleanup_http_client()

            # All tasks should be cleaned up
            assert len(stage._cleanup_tasks) == 0
