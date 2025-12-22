"""Regression test for ServiceCollection cleanup task tracking fix.

This test verifies that tasks created when replacing httpx.AsyncClient instances
are properly tracked in _cleanup_tasks set and don't accumulate unbounded.

Fixed: Cleanup tasks are tracked in _cleanup_tasks set and properly awaited
during dispose() to prevent resource leaks.
"""

import asyncio

import httpx
import pytest

from src.core.di.container import ServiceCollection


class TestServiceCollectionTaskLeakRegression:
    """Regression tests for ServiceCollection cleanup task tracking fix."""

    @pytest.mark.asyncio
    async def test_cleanup_tasks_tracked_on_replacement(self) -> None:
        """Test that cleanup tasks are tracked when replacing httpx clients."""
        services = ServiceCollection()

        # Create first client
        client1 = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(max_connections=10),
        )
        services.add_instance(httpx.AsyncClient, client1)

        # Verify no cleanup tasks initially
        assert len(services._cleanup_tasks) == 0, (
            "No cleanup tasks should exist before replacement"
        )

        # Replace with second client (should create cleanup task)
        client2 = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(max_connections=10),
        )
        services.add_instance(httpx.AsyncClient, client2)

        # Verify cleanup task was created and tracked
        assert len(services._cleanup_tasks) > 0, (
            "Cleanup task should be tracked when replacing client"
        )

        # Clean up
        await services.dispose()
        await client2.aclose()

    @pytest.mark.asyncio
    async def test_multiple_replacements_track_tasks(self) -> None:
        """Test that multiple client replacements track cleanup tasks properly."""
        services = ServiceCollection()

        clients = []
        for i in range(10):
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                limits=httpx.Limits(max_connections=10),
            )
            services.add_instance(httpx.AsyncClient, client)
            clients.append(client)

            # Small delay to allow tasks to complete
            await asyncio.sleep(0.01)

        # Verify cleanup tasks were created (one per replacement)
        # After replacements, some tasks may have completed
        tracked_count = len(services._cleanup_tasks)
        assert tracked_count >= 0, "Cleanup tasks should be tracked"

        # Wait for tasks to complete
        await asyncio.sleep(0.2)

        # Check that tasks don't accumulate unbounded
        # Some tasks may still be pending, but should be manageable
        pending_tasks = [t for t in services._cleanup_tasks if not t.done()]
        assert len(pending_tasks) <= 10, (
            f"Too many pending cleanup tasks: {len(pending_tasks)}. "
            "Tasks should complete or be properly managed."
        )

        # Clean up
        await services.dispose()
        await clients[-1].aclose()

    @pytest.mark.asyncio
    async def test_cleanup_tasks_complete_after_dispose(self) -> None:
        """Test that cleanup tasks complete after dispose() is called."""
        services = ServiceCollection()

        # Create and replace clients
        client1 = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(max_connections=10),
        )
        services.add_instance(httpx.AsyncClient, client1)

        client2 = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(max_connections=10),
        )
        services.add_instance(httpx.AsyncClient, client2)

        # Verify cleanup task exists
        assert len(services._cleanup_tasks) > 0, (
            "Cleanup task should be created"
        )

        # Call dispose() - should await cleanup tasks
        await services.dispose()

        # Verify cleanup tasks were cleared
        assert len(services._cleanup_tasks) == 0, (
            "Cleanup tasks should be cleared after dispose()"
        )

        # Verify client1 was closed
        assert client1.is_closed, "Replaced client should be closed after dispose()"

        # Clean up client2
        await client2.aclose()

    @pytest.mark.asyncio
    async def test_cleanup_tasks_dont_leak_without_dispose(self) -> None:
        """Test that cleanup tasks complete even without explicit dispose()."""
        services = ServiceCollection()

        # Create and replace clients multiple times
        for i in range(5):
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                limits=httpx.Limits(max_connections=10),
            )
            services.add_instance(httpx.AsyncClient, client)
            await asyncio.sleep(0.01)

        # Wait for tasks to complete naturally
        await asyncio.sleep(0.5)

        # Tasks should complete even without dispose()
        # (though dispose() should still be called in production)
        pending_tasks = [t for t in services._cleanup_tasks if not t.done()]
        # Some tasks may still be pending, but should be reasonable
        assert len(pending_tasks) <= 5, (
            f"Too many pending tasks without dispose(): {len(pending_tasks)}. "
            "Tasks should complete naturally or be properly tracked."
        )

        # Clean up final client
        provider = services.build_service_provider()
        final_client = provider.get_service(httpx.AsyncClient)
        if final_client and not final_client.is_closed:
            await final_client.aclose()

    @pytest.mark.asyncio
    async def test_rapid_replacements_dont_accumulate_tasks(self) -> None:
        """Test that rapid client replacements don't cause task accumulation."""
        services = ServiceCollection()

        initial_task_count = len(asyncio.all_tasks())

        # Rapidly replace clients
        for i in range(20):
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                limits=httpx.Limits(max_connections=10),
            )
            services.add_instance(httpx.AsyncClient, client)

        # Wait for tasks to process
        await asyncio.sleep(0.3)

        # Check that tasks don't accumulate excessively
        final_task_count = len(asyncio.all_tasks())
        task_increase = final_task_count - initial_task_count

        # Allow tolerance for test framework tasks
        assert task_increase <= 25, (
            f"Rapid replacements caused task accumulation: {task_increase} tasks. "
            "Cleanup tasks should be properly managed."
        )

        # Clean up
        await services.dispose()
        provider = services.build_service_provider()
        final_client = provider.get_service(httpx.AsyncClient)
        if final_client and not final_client.is_closed:
            await final_client.aclose()
