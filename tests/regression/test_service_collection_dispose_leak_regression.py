"""Regression test for ServiceCollection.dispose() leak fix.

This test verifies that ServiceCollection.dispose() is called during normal
application shutdown to ensure cleanup tasks are properly awaited.
"""

import httpx
import pytest
from src.core.di.container import ServiceCollection


@pytest.mark.asyncio
async def test_dispose_called_during_shutdown():
    """Test that dispose() is called and cleanup tasks are awaited."""
    services = ServiceCollection()

    # Create first client
    client1 = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    services.add_instance(httpx.AsyncClient, client1)

    # Replace with second client (creates cleanup task)
    client2 = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    services.add_instance(httpx.AsyncClient, client2)

    # Verify cleanup task was created
    assert len(services._cleanup_tasks) == 1

    # Call dispose() (simulating what happens during shutdown)
    await services.dispose()

    # Verify cleanup tasks were awaited and cleared
    assert len(services._cleanup_tasks) == 0

    # Verify client1 was closed
    assert client1.is_closed

    # Clean up client2
    await client2.aclose()


@pytest.mark.asyncio
async def test_dispose_handles_multiple_cleanup_tasks():
    """Test that dispose() handles multiple cleanup tasks correctly."""
    services = ServiceCollection()

    clients = []
    for _i in range(5):
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        services.add_instance(httpx.AsyncClient, client)
        clients.append(client)

    # Verify cleanup tasks were created
    assert len(services._cleanup_tasks) == 4  # 4 replacements = 4 cleanup tasks

    # Call dispose()
    await services.dispose()

    # Verify all cleanup tasks were awaited and cleared
    assert len(services._cleanup_tasks) == 0

    # Verify all but the last client were closed
    for client in clients[:-1]:
        assert client.is_closed

    # Clean up last client
    await clients[-1].aclose()


@pytest.mark.asyncio
async def test_dispose_idempotent():
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

    # Should not raise exception and should be idempotent
    assert len(services._cleanup_tasks) == 0

    # Clean up
    await client2.aclose()
