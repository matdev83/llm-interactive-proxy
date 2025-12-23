"""Regression test for ServiceCollection.dispose() not being called during normal shutdown.

This test verifies that ServiceCollection.dispose() properly cleans up HTTP client
cleanup tasks to prevent resource leaks. The fix ensures that dispose() is called
during application shutdown to await all pending cleanup tasks.
"""

import asyncio

import httpx
import pytest
from src.core.di.container import ServiceCollection


class TestServiceCollectionDisposeNotCalledRegression:
    """Regression tests for ServiceCollection.dispose() cleanup fix."""

    @pytest.mark.asyncio
    async def test_dispose_awaits_cleanup_tasks(self) -> None:
        """Test that dispose() properly awaits cleanup tasks."""
        services = ServiceCollection()

        # Register first client
        client1 = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        services.add_instance(httpx.AsyncClient, client1)

        # Replace with second client (this creates cleanup task)
        client2 = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        services.add_instance(httpx.AsyncClient, client2)

        # Verify cleanup task was created
        pending_tasks = [t for t in services._cleanup_tasks if not t.done()]
        assert (
            len(pending_tasks) > 0
        ), "Cleanup task should be created when replacing client"

        # Verify client1 is still open (cleanup task not awaited yet)
        assert not client1.is_closed, "Client1 should still be open before dispose()"

        # Call dispose() - this should await cleanup tasks
        await services.dispose()

        # Verify cleanup tasks were awaited
        await asyncio.sleep(0.1)  # Give tasks time to complete
        pending_after = [t for t in services._cleanup_tasks if not t.done()]
        assert (
            len(pending_after) == 0
        ), "All cleanup tasks should be completed after dispose()"

        # Verify client1 was closed (cleanup task completed)
        assert (
            client1.is_closed
        ), "Client1 should be closed after dispose() awaits cleanup tasks"

        # Cleanup client2
        await client2.aclose()

    @pytest.mark.asyncio
    async def test_dispose_cleans_up_multiple_clients(self) -> None:
        """Test that dispose() cleans up multiple replaced clients."""
        services = ServiceCollection()

        # Create and replace multiple clients
        clients = []
        for _i in range(10):
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
                limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            )
            services.add_instance(httpx.AsyncClient, client)
            clients.append(client)

        # Verify cleanup tasks were created for all but the last client
        pending_tasks = [t for t in services._cleanup_tasks if not t.done()]
        assert (
            len(pending_tasks) == 9
        ), "Should have 9 cleanup tasks (one for each replaced client)"

        # Verify all but last client are still open
        open_clients = [c for c in clients[:-1] if not c.is_closed]
        assert (
            len(open_clients) == 9
        ), "All replaced clients should still be open before dispose()"

        # Call dispose() - should clean up all clients
        await services.dispose()

        # Verify all cleanup tasks were completed
        await asyncio.sleep(0.1)  # Give tasks time to complete
        pending_after = [t for t in services._cleanup_tasks if not t.done()]
        assert len(pending_after) == 0, "All cleanup tasks should be completed"

        # Verify all replaced clients were closed
        open_after = [c for c in clients[:-1] if not c.is_closed]
        assert (
            len(open_after) == 0
        ), "All replaced clients should be closed after dispose()"

        # Cleanup last client
        await clients[-1].aclose()

    @pytest.mark.asyncio
    async def test_dispose_idempotent(self) -> None:
        """Test that dispose() can be called multiple times safely."""
        services = ServiceCollection()

        client1 = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        services.add_instance(httpx.AsyncClient, client1)

        client2 = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        services.add_instance(httpx.AsyncClient, client2)

        # Call dispose() multiple times
        await services.dispose()
        await services.dispose()
        await services.dispose()

        # Should not raise exceptions and cleanup should be complete
        assert client1.is_closed, "Client1 should be closed after dispose()"
        assert len(services._cleanup_tasks) == 0, "Cleanup tasks should be cleared"

        # Cleanup client2
        await client2.aclose()

    @pytest.mark.asyncio
    async def test_dispose_without_cleanup_tasks(self) -> None:
        """Test that dispose() works correctly when there are no cleanup tasks."""
        services = ServiceCollection()

        # Add a client without replacing it (no cleanup task)
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        services.add_instance(httpx.AsyncClient, client)

        # Verify no cleanup tasks
        assert len(services._cleanup_tasks) == 0, "No cleanup tasks should exist"

        # Dispose should work without errors
        await services.dispose()

        # Cleanup client
        await client.aclose()
