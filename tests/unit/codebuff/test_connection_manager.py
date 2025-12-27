"""
Unit tests for Codebuff Connection Manager.

These tests verify the functionality of connection management, session tracking,
heartbeat monitoring, and subscription management.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.codebuff.connection_manager import ConnectionManager
from src.codebuff.exceptions import CodebuffSessionError


class TestConnectionManager:
    """Test suite for ConnectionManager."""

    @pytest.mark.asyncio
    async def test_connect_creates_session(self):
        """Test that connecting creates a session entry."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"

        await manager.connect(websocket, session_id)

        session = await manager.get_session(websocket)
        assert session is not None
        assert session.session_id == session_id
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.last_seen, datetime)

    @pytest.mark.asyncio
    async def test_connect_duplicate_session_id_raises_error(self):
        """Test that connecting with duplicate session ID raises error."""
        manager = ConnectionManager()
        websocket1 = MagicMock()
        websocket2 = MagicMock()
        session_id = "test-session-123"

        await manager.connect(websocket1, session_id)

        with pytest.raises(CodebuffSessionError) as exc_info:
            await manager.connect(websocket2, session_id)

        assert "already in use" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_disconnect_removes_session(self):
        """Test that disconnecting removes the session."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"

        await manager.connect(websocket, session_id)
        assert await manager.get_session(websocket) is not None

        await manager.disconnect(websocket)
        assert await manager.get_session(websocket) is None

    @pytest.mark.asyncio
    async def test_disconnect_unknown_connection_does_not_raise(self):
        """Test that disconnecting unknown connection doesn't raise error."""
        manager = ConnectionManager()
        websocket = MagicMock()

        # Should not raise
        await manager.disconnect(websocket)

    @pytest.mark.asyncio
    async def test_get_session_returns_none_for_unknown_connection(self):
        """Test that get_session returns None for unknown connection."""
        manager = ConnectionManager()
        websocket = MagicMock()

        session = await manager.get_session(websocket)
        assert session is None

    @pytest.mark.asyncio
    async def test_update_last_seen_updates_timestamp(self):
        """Test that update_last_seen updates the timestamp."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"

        await manager.connect(websocket, session_id)
        session = await manager.get_session(websocket)
        initial_last_seen = session.last_seen

        # Advance time to ensure timestamp difference
        from freezegun import freeze_time

        with freeze_time("2024-01-01 12:00:00") as frozen_time:
            datetime.utcnow()
            frozen_time.tick(timedelta(microseconds=10000))  # Advance 0.01 seconds
            await manager.update_last_seen(websocket)

        session = await manager.get_session(websocket)
        assert session.last_seen > initial_last_seen

    @pytest.mark.asyncio
    async def test_update_last_seen_unknown_connection_raises_error(self):
        """Test that update_last_seen raises error for unknown connection."""
        manager = ConnectionManager()
        websocket = MagicMock()

        with pytest.raises(CodebuffSessionError):
            await manager.update_last_seen(websocket)

    @pytest.mark.asyncio
    async def test_subscribe_adds_subscriptions(self):
        """Test that subscribe adds topics to session."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"
        topics = ["topic1", "topic2", "topic3"]

        await manager.connect(websocket, session_id)
        await manager.subscribe(websocket, topics)

        session = await manager.get_session(websocket)
        for topic in topics:
            assert topic in session.subscriptions

    @pytest.mark.asyncio
    async def test_subscribe_unknown_connection_raises_error(self):
        """Test that subscribe raises error for unknown connection."""
        manager = ConnectionManager()
        websocket = MagicMock()
        topics = ["topic1"]

        with pytest.raises(CodebuffSessionError):
            await manager.subscribe(websocket, topics)

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_subscriptions(self):
        """Test that unsubscribe removes topics from session."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"
        topics = ["topic1", "topic2", "topic3"]

        await manager.connect(websocket, session_id)
        await manager.subscribe(websocket, topics)

        # Verify subscriptions exist
        session = await manager.get_session(websocket)
        for topic in topics:
            assert topic in session.subscriptions

        # Unsubscribe
        await manager.unsubscribe(websocket, topics)

        # Verify subscriptions removed
        session = await manager.get_session(websocket)
        for topic in topics:
            assert topic not in session.subscriptions

    @pytest.mark.asyncio
    async def test_unsubscribe_unknown_connection_raises_error(self):
        """Test that unsubscribe raises error for unknown connection."""
        manager = ConnectionManager()
        websocket = MagicMock()
        topics = ["topic1"]

        with pytest.raises(CodebuffSessionError):
            await manager.unsubscribe(websocket, topics)

    @pytest.mark.asyncio
    async def test_get_subscribers_returns_subscribed_connections(self):
        """Test that get_subscribers returns correct connections."""
        manager = ConnectionManager()
        websocket1 = MagicMock()
        websocket2 = MagicMock()
        websocket3 = MagicMock()
        topic = "test-topic"

        await manager.connect(websocket1, "session1")
        await manager.connect(websocket2, "session2")
        await manager.connect(websocket3, "session3")

        # Subscribe websocket1 and websocket2 to topic
        await manager.subscribe(websocket1, [topic])
        await manager.subscribe(websocket2, [topic])

        subscribers = await manager.get_subscribers(topic)
        assert websocket1 in subscribers
        assert websocket2 in subscribers
        assert websocket3 not in subscribers

    @pytest.mark.asyncio
    async def test_get_subscribers_returns_empty_list_for_unknown_topic(self):
        """Test that get_subscribers returns empty list for unknown topic."""
        manager = ConnectionManager()

        subscribers = await manager.get_subscribers("unknown-topic")
        assert subscribers == []

    @pytest.mark.asyncio
    async def test_disconnect_removes_all_subscriptions(self):
        """Test that disconnect removes all subscriptions for connection."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"
        topics = ["topic1", "topic2", "topic3"]

        await manager.connect(websocket, session_id)
        await manager.subscribe(websocket, topics)

        # Verify subscriptions exist
        for topic in topics:
            subscribers = await manager.get_subscribers(topic)
            assert websocket in subscribers

        # Disconnect
        await manager.disconnect(websocket)

        # Verify all subscriptions removed
        for topic in topics:
            subscribers = await manager.get_subscribers(topic)
            assert websocket not in subscribers

    @pytest.mark.asyncio
    async def test_cleanup_stale_connections_removes_old_connections(self):
        """Test that cleanup removes connections exceeding heartbeat timeout."""
        # Use a short timeout for testing
        manager = ConnectionManager(heartbeat_timeout_seconds=1)
        websocket1 = MagicMock()
        websocket1.close = AsyncMock()
        websocket2 = MagicMock()
        websocket2.close = AsyncMock()

        await manager.connect(websocket1, "session1")
        await manager.connect(websocket2, "session2")

        # Manually set last_seen to be old for websocket1
        from freezegun import freeze_time

        with freeze_time("2024-01-01 12:00:00"):
            session1 = await manager.get_session(websocket1)
            session1.last_seen = datetime.utcnow() - timedelta(seconds=2)

        # Update websocket2 to be recent
        await manager.update_last_seen(websocket2)

        # Run cleanup
        await manager.cleanup_stale_connections()

        # Verify websocket1 was removed and websocket2 remains
        assert await manager.get_session(websocket1) is None
        assert await manager.get_session(websocket2) is not None
        websocket1.close.assert_called_once()
        websocket2.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_stale_connections_handles_close_errors(self):
        """Test that cleanup handles errors when closing connections."""
        manager = ConnectionManager(heartbeat_timeout_seconds=1)
        websocket = MagicMock()
        websocket.close = AsyncMock(side_effect=Exception("Close failed"))

        await manager.connect(websocket, "session1")

        # Make connection stale
        from freezegun import freeze_time

        with freeze_time("2024-01-01 12:00:00"):
            fixed_time = datetime(2024, 1, 1, 12, 0, 0)
            session = await manager.get_session(websocket)
            session.last_seen = fixed_time - timedelta(seconds=2)

        # Run cleanup - should not raise
        await manager.cleanup_stale_connections()

        # Verify connection was still removed despite close error
        assert await manager.get_session(websocket) is None

    @pytest.mark.asyncio
    async def test_cleanup_stale_connections_does_nothing_when_all_fresh(self):
        """Test that cleanup does nothing when all connections are fresh."""
        manager = ConnectionManager(heartbeat_timeout_seconds=60)
        websocket = MagicMock()
        websocket.close = AsyncMock()

        await manager.connect(websocket, "session1")
        await manager.update_last_seen(websocket)

        # Run cleanup
        await manager.cleanup_stale_connections()

        # Verify connection still exists
        assert await manager.get_session(websocket) is not None
        websocket.close.assert_not_called()
