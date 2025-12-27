"""Regression test for ConnectionManager memory leak fix.

This test verifies that ConnectionManager properly enforces max_connections limit
and cleans up stale connections to prevent unbounded memory growth.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.codebuff.connection_manager import ConnectionManager


class TestConnectionManagerLeakRegression:
    """Regression tests for ConnectionManager memory leak fix."""

    @pytest.fixture
    def manager(self):
        """Create a ConnectionManager with small limits for testing."""
        return ConnectionManager(
            heartbeat_timeout_seconds=60,
            max_connections=20,  # Small limit for testing
        )

    @pytest.mark.asyncio
    async def test_max_connections_enforced(self, manager: ConnectionManager) -> None:
        """Test that max_connections limit is enforced."""
        # Create connections up to the limit
        mock_websockets = []
        for i in range(manager._max_connections):
            mock_ws = MagicMock()
            mock_ws.close = MagicMock()
            session_id = f"session-{i}"
            await manager.connect(mock_ws, session_id)
            mock_websockets.append((mock_ws, session_id))

        # Verify we're at the limit
        assert len(manager._connections) == manager._max_connections

        # Try to add one more - should raise CodebuffSessionError
        from src.codebuff.exceptions import CodebuffSessionError

        extra_ws = MagicMock()
        with pytest.raises(CodebuffSessionError):
            await manager.connect(extra_ws, "session-extra")

    @pytest.mark.asyncio
    async def test_stale_connections_cleaned_up(
        self, manager: ConnectionManager
    ) -> None:
        """Test that stale connections are cleaned up."""
        # Create some connections
        mock_websockets = []
        for i in range(10):
            mock_ws = MagicMock()
            mock_ws.close = AsyncMock()
            session_id = f"session-{i}"
            await manager.connect(mock_ws, session_id)
            mock_websockets.append((mock_ws, session_id))

        initial_count = len(manager._connections)

        # Make some connections stale by setting old last_seen
        stale_count = 5
        for mock_ws, _session_id in mock_websockets[:stale_count]:
            session = await manager.get_session(mock_ws)
            if session:
                session.last_seen = datetime.utcnow() - timedelta(seconds=120)

        # Clean up stale connections
        await manager.cleanup_stale_connections()

        # Verify stale connections were removed
        final_count = len(manager._connections)
        assert final_count == initial_count - stale_count, (
            f"Expected {initial_count - stale_count} connections after cleanup, "
            f"got {final_count}. Stale connections were not properly cleaned up."
        )

    @pytest.mark.asyncio
    async def test_subscriptions_cleaned_up_on_disconnect(
        self, manager: ConnectionManager
    ) -> None:
        """Test that subscriptions are cleaned up when connections disconnect."""
        # Create a connection and subscribe to topics
        mock_ws = MagicMock()
        session_id = "test-session"
        await manager.connect(mock_ws, session_id)

        topics = ["topic-1", "topic-2", "topic-3"]
        await manager.subscribe(mock_ws, topics)

        # Verify subscriptions exist
        for topic in topics:
            subscribers = await manager.get_subscribers(topic)
            assert mock_ws in subscribers

        # Disconnect
        await manager.disconnect(mock_ws)

        # Verify subscriptions are cleaned up
        for topic in topics:
            subscribers = await manager.get_subscribers(topic)
            assert mock_ws not in subscribers
            # Empty topic sets should be removed
            assert topic not in manager._subscriptions

    @pytest.mark.asyncio
    async def test_connections_bounded_by_limit(
        self, manager: ConnectionManager
    ) -> None:
        """Test that connections don't exceed max_connections limit."""
        # Create many connections
        num_connections = manager._max_connections + 50
        mock_websockets = []

        created_count = 0
        for i in range(num_connections):
            mock_ws = MagicMock()
            mock_ws.close = MagicMock()
            session_id = f"session-{i}"

            try:
                await manager.connect(mock_ws, session_id)
                created_count += 1
                mock_websockets.append((mock_ws, session_id))
            except Exception:
                # Expected to fail when limit is reached
                pass

        # Verify we didn't exceed the limit
        assert len(manager._connections) <= manager._max_connections, (
            f"Connections ({len(manager._connections)}) exceeded "
            f"max_connections ({manager._max_connections})."
        )

    @pytest.mark.asyncio
    async def test_session_id_mapping_cleaned_up(
        self, manager: ConnectionManager
    ) -> None:
        """Test that session_id_to_websocket mapping is cleaned up on disconnect."""
        mock_ws = MagicMock()
        session_id = "test-session"
        await manager.connect(mock_ws, session_id)

        # Verify mapping exists
        assert session_id in manager._session_id_to_websocket

        # Disconnect
        await manager.disconnect(mock_ws)

        # Verify mapping is cleaned up
        assert session_id not in manager._session_id_to_websocket

    @pytest.mark.asyncio
    async def test_cleanup_stale_connections_handles_errors(
        self, manager: ConnectionManager
    ) -> None:
        """Test that cleanup_stale_connections handles errors gracefully."""
        # Create a stale connection
        mock_ws = MagicMock()
        mock_ws.close = AsyncMock(side_effect=Exception("Close failed"))
        session_id = "stale-session"
        await manager.connect(mock_ws, session_id)

        # Make it stale
        session = await manager.get_session(mock_ws)
        if session:
            session.last_seen = datetime.utcnow() - timedelta(seconds=120)

        # Cleanup should handle the error and still remove the connection
        await manager.cleanup_stale_connections()

        # Connection should still be removed even if close() failed
        assert (
            mock_ws not in manager._connections
        ), "Stale connection should be removed even if close() fails."
        assert session_id not in manager._session_id_to_websocket
