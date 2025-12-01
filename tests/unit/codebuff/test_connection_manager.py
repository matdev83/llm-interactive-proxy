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

    def test_connect_creates_session(self):
        """Test that connecting creates a session entry."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"

        manager.connect(websocket, session_id)

        session = manager.get_session(websocket)
        assert session is not None
        assert session.session_id == session_id
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.last_seen, datetime)

    def test_connect_duplicate_session_id_raises_error(self):
        """Test that connecting with duplicate session ID raises error."""
        manager = ConnectionManager()
        websocket1 = MagicMock()
        websocket2 = MagicMock()
        session_id = "test-session-123"

        manager.connect(websocket1, session_id)

        with pytest.raises(CodebuffSessionError) as exc_info:
            manager.connect(websocket2, session_id)

        assert "already in use" in str(exc_info.value)

    def test_disconnect_removes_session(self):
        """Test that disconnecting removes the session."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"

        manager.connect(websocket, session_id)
        assert manager.get_session(websocket) is not None

        manager.disconnect(websocket)
        assert manager.get_session(websocket) is None

    def test_disconnect_unknown_connection_does_not_raise(self):
        """Test that disconnecting unknown connection doesn't raise error."""
        manager = ConnectionManager()
        websocket = MagicMock()

        # Should not raise
        manager.disconnect(websocket)

    def test_get_session_returns_none_for_unknown_connection(self):
        """Test that get_session returns None for unknown connection."""
        manager = ConnectionManager()
        websocket = MagicMock()

        session = manager.get_session(websocket)
        assert session is None

    def test_update_last_seen_updates_timestamp(self):
        """Test that update_last_seen updates the timestamp."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"

        manager.connect(websocket, session_id)
        session = manager.get_session(websocket)
        initial_last_seen = session.last_seen

        # Wait a bit to ensure timestamp difference
        import time

        time.sleep(0.01)

        manager.update_last_seen(websocket)

        session = manager.get_session(websocket)
        assert session.last_seen > initial_last_seen

    def test_update_last_seen_unknown_connection_raises_error(self):
        """Test that update_last_seen raises error for unknown connection."""
        manager = ConnectionManager()
        websocket = MagicMock()

        with pytest.raises(CodebuffSessionError):
            manager.update_last_seen(websocket)

    def test_subscribe_adds_subscriptions(self):
        """Test that subscribe adds topics to session."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"
        topics = ["topic1", "topic2", "topic3"]

        manager.connect(websocket, session_id)
        manager.subscribe(websocket, topics)

        session = manager.get_session(websocket)
        for topic in topics:
            assert topic in session.subscriptions

    def test_subscribe_unknown_connection_raises_error(self):
        """Test that subscribe raises error for unknown connection."""
        manager = ConnectionManager()
        websocket = MagicMock()
        topics = ["topic1"]

        with pytest.raises(CodebuffSessionError):
            manager.subscribe(websocket, topics)

    def test_unsubscribe_removes_subscriptions(self):
        """Test that unsubscribe removes topics from session."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"
        topics = ["topic1", "topic2", "topic3"]

        manager.connect(websocket, session_id)
        manager.subscribe(websocket, topics)

        # Verify subscriptions exist
        session = manager.get_session(websocket)
        for topic in topics:
            assert topic in session.subscriptions

        # Unsubscribe
        manager.unsubscribe(websocket, topics)

        # Verify subscriptions removed
        session = manager.get_session(websocket)
        for topic in topics:
            assert topic not in session.subscriptions

    def test_unsubscribe_unknown_connection_raises_error(self):
        """Test that unsubscribe raises error for unknown connection."""
        manager = ConnectionManager()
        websocket = MagicMock()
        topics = ["topic1"]

        with pytest.raises(CodebuffSessionError):
            manager.unsubscribe(websocket, topics)

    def test_get_subscribers_returns_subscribed_connections(self):
        """Test that get_subscribers returns correct connections."""
        manager = ConnectionManager()
        websocket1 = MagicMock()
        websocket2 = MagicMock()
        websocket3 = MagicMock()
        topic = "test-topic"

        manager.connect(websocket1, "session1")
        manager.connect(websocket2, "session2")
        manager.connect(websocket3, "session3")

        # Subscribe websocket1 and websocket2 to topic
        manager.subscribe(websocket1, [topic])
        manager.subscribe(websocket2, [topic])

        subscribers = manager.get_subscribers(topic)
        assert websocket1 in subscribers
        assert websocket2 in subscribers
        assert websocket3 not in subscribers

    def test_get_subscribers_returns_empty_list_for_unknown_topic(self):
        """Test that get_subscribers returns empty list for unknown topic."""
        manager = ConnectionManager()

        subscribers = manager.get_subscribers("unknown-topic")
        assert subscribers == []

    def test_disconnect_removes_all_subscriptions(self):
        """Test that disconnect removes all subscriptions for connection."""
        manager = ConnectionManager()
        websocket = MagicMock()
        session_id = "test-session-123"
        topics = ["topic1", "topic2", "topic3"]

        manager.connect(websocket, session_id)
        manager.subscribe(websocket, topics)

        # Verify subscriptions exist
        for topic in topics:
            assert websocket in manager.get_subscribers(topic)

        # Disconnect
        manager.disconnect(websocket)

        # Verify all subscriptions removed
        for topic in topics:
            assert websocket not in manager.get_subscribers(topic)

    @pytest.mark.asyncio
    async def test_cleanup_stale_connections_removes_old_connections(self):
        """Test that cleanup removes connections exceeding heartbeat timeout."""
        # Use a short timeout for testing
        manager = ConnectionManager(heartbeat_timeout_seconds=1)
        websocket1 = MagicMock()
        websocket1.close = AsyncMock()
        websocket2 = MagicMock()
        websocket2.close = AsyncMock()

        manager.connect(websocket1, "session1")
        manager.connect(websocket2, "session2")

        # Manually set last_seen to be old for websocket1
        session1 = manager.get_session(websocket1)
        session1.last_seen = datetime.utcnow() - timedelta(seconds=2)

        # Update websocket2 to be recent
        manager.update_last_seen(websocket2)

        # Run cleanup
        await manager.cleanup_stale_connections()

        # Verify websocket1 was removed and websocket2 remains
        assert manager.get_session(websocket1) is None
        assert manager.get_session(websocket2) is not None
        websocket1.close.assert_called_once()
        websocket2.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_stale_connections_handles_close_errors(self):
        """Test that cleanup handles errors when closing connections."""
        manager = ConnectionManager(heartbeat_timeout_seconds=1)
        websocket = MagicMock()
        websocket.close = AsyncMock(side_effect=Exception("Close failed"))

        manager.connect(websocket, "session1")

        # Make connection stale
        session = manager.get_session(websocket)
        session.last_seen = datetime.utcnow() - timedelta(seconds=2)

        # Run cleanup - should not raise
        await manager.cleanup_stale_connections()

        # Verify connection was still removed despite close error
        assert manager.get_session(websocket) is None

    @pytest.mark.asyncio
    async def test_cleanup_stale_connections_does_nothing_when_all_fresh(self):
        """Test that cleanup does nothing when all connections are fresh."""
        manager = ConnectionManager(heartbeat_timeout_seconds=60)
        websocket = MagicMock()
        websocket.close = AsyncMock()

        manager.connect(websocket, "session1")
        manager.update_last_seen(websocket)

        # Run cleanup
        await manager.cleanup_stale_connections()

        # Verify connection still exists
        assert manager.get_session(websocket) is not None
        websocket.close.assert_not_called()
