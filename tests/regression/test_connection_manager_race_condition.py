"""
Regression test for ConnectionManager race condition fix.

Tests that all shared state access is properly protected
by the async lock.
"""

import asyncio

import pytest
from src.codebuff.connection_manager import ConnectionManager


class MockWebSocket:
    """Mock WebSocket for testing."""

    def __init__(self, ws_id: str):
        self.id = ws_id
        self.closed = False

    async def close(self, code=1000, reason=""):
        self.closed = True


@pytest.mark.asyncio
async def test_connection_manager_concurrent_connect():
    """Test that concurrent connects don't create duplicate sessions."""
    manager = ConnectionManager(max_connections=100)

    # Try to connect same session ID from multiple coroutines
    ws1 = MockWebSocket("ws_1")
    ws2 = MockWebSocket("ws_2")
    session_id = "session_123"

    async def connect_ws(ws):
        try:
            await manager.connect(ws, session_id)
            return True
        except Exception:
            return False

    # Run concurrent connects
    results = await asyncio.gather(connect_ws(ws1), connect_ws(ws2))

    # Exactly one should succeed
    success_count = sum(results)
    assert success_count == 1, f"Expected 1 success, got {success_count}"

    # Session should be registered with exactly one websocket
    session = await manager.get_session(ws1)
    ws1_has_session = session is not None

    session2 = await manager.get_session(ws2)
    ws2_has_session = session2 is not None

    assert (
        ws1_has_session != ws2_has_session
    ), "Only one websocket should have the session"


@pytest.mark.asyncio
async def test_connection_manager_concurrent_subscribe():
    """Test that concurrent subscribes don't corrupt subscription sets."""
    manager = ConnectionManager()
    ws = MockWebSocket("ws_test")

    await manager.connect(ws, "session_sub")

    # Subscribe to many topics concurrently
    async def subscribe_batch(start, end):
        topics = [f"topic_{i}" for i in range(start, end)]
        await manager.subscribe(ws, topics)

    # Run concurrent subscriptions
    await asyncio.gather(
        subscribe_batch(0, 50),
        subscribe_batch(50, 100),
        subscribe_batch(100, 150),
    )

    # Disconnect and check subscriptions were tracked correctly
    session = await manager.get_session(ws)
    assert session is not None
    assert len(session.subscriptions) == 150


@pytest.mark.asyncio
async def test_connection_manager_concurrent_disconnect():
    """Test that concurrent disconnects don't cause key errors."""
    manager = ConnectionManager()
    ws1 = MockWebSocket("ws_1")
    ws2 = MockWebSocket("ws_2")

    await manager.connect(ws1, "session_1")
    await manager.connect(ws2, "session_2")

    # Subscribe to topics
    await manager.subscribe(ws1, ["topic_a", "topic_b"])
    await manager.subscribe(ws2, ["topic_c", "topic_d"])

    # Disconnect concurrently
    await asyncio.gather(manager.disconnect(ws1), manager.disconnect(ws2))

    # Both sessions should be gone
    assert await manager.get_session(ws1) is None
    assert await manager.get_session(ws2) is None


@pytest.mark.asyncio
async def test_connection_manager_concurrent_update_last_seen():
    """Test that concurrent last_seen updates don't corrupt state."""
    manager = ConnectionManager()
    ws = MockWebSocket("ws_update")

    await manager.connect(ws, "session_update")

    # Update last_seen concurrently many times
    async def update_last_seen():
        for _ in range(10):
            await manager.update_last_seen(ws)

    await asyncio.gather(update_last_seen(), update_last_seen(), update_last_seen())

    # Session should still be valid
    session = await manager.get_session(ws)
    assert session is not None
    assert session.session_id == "session_update"


@pytest.mark.asyncio
async def test_connection_manager_max_connections_with_race():
    """Test that max_connections limit works under concurrent pressure."""
    manager = ConnectionManager(max_connections=5)

    # Try to connect more than max connections
    async def connect_session(i):
        ws = MockWebSocket(f"ws_{i}")
        try:
            await manager.connect(ws, f"session_{i}")
            return ws
        except Exception:
            return None

    # Launch 10 concurrent connections
    results = await asyncio.gather(*[connect_session(i) for i in range(10)])

    # Count successful connections
    successful = [ws for ws in results if ws is not None]
    assert len(successful) <= 5, "Should not exceed max_connections"


@pytest.mark.asyncio
async def test_connection_manager_cleanup_with_concurrent_operations():
    """Test that cleanup doesn't interfere with concurrent operations."""
    manager = ConnectionManager(heartbeat_timeout_seconds=1)

    # Create several connections
    websockets = []
    for i in range(10):
        ws = MockWebSocket(f"ws_{i}")
        await manager.connect(ws, f"session_{i}")
        websockets.append(ws)

    # Run cleanup concurrently with other operations
    async def run_operations():
        # Update last seen for some
        await asyncio.gather(*[manager.update_last_seen(ws) for ws in websockets[:5]])

        # Subscribe some
        await asyncio.gather(
            *[
                manager.subscribe(ws, [f"topic_{i}"])
                for i, ws in enumerate(websockets[:5])
            ]
        )

    # Run operations and cleanup concurrently
    await asyncio.gather(
        run_operations(),
        manager.cleanup_stale_connections(),
    )

    # Remaining connections should still be valid
    for ws in websockets[:5]:
        session = await manager.get_session(ws)
        assert session is not None
