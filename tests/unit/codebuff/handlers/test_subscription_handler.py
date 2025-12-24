"""
Unit tests for SubscriptionHandler.

These tests verify the functionality of subscription management,
including subscribe, unsubscribe, and error handling.
"""

from unittest.mock import MagicMock

import pytest
from src.codebuff.connection_manager import ConnectionManager
from src.codebuff.exceptions import CodebuffError, CodebuffSessionError
from src.codebuff.handlers.subscription_handler import SubscriptionHandler


class TestSubscriptionHandler:
    """Test suite for SubscriptionHandler."""

    @pytest.mark.asyncio
    async def test_handle_subscribe_adds_subscriptions(self):
        """Test that handle_subscribe adds subscriptions to session."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        await connection_manager.connect(websocket, session_id)

        topics = ["topic1", "topic2", "topic3"]

        # Act
        await subscription_handler.handle_subscribe(websocket, topics)

        # Assert
        session = await connection_manager.get_session(websocket)
        assert session is not None
        for topic in topics:
            assert topic in session.subscriptions
            subscribers = await connection_manager.get_subscribers(topic)
            assert websocket in subscribers

    @pytest.mark.asyncio
    async def test_handle_subscribe_single_topic(self):
        """Test that handle_subscribe works with a single topic."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        await connection_manager.connect(websocket, session_id)

        topics = ["single-topic"]

        # Act
        await subscription_handler.handle_subscribe(websocket, topics)

        # Assert
        session = await connection_manager.get_session(websocket)
        assert session is not None
        assert "single-topic" in session.subscriptions
        subscribers = await connection_manager.get_subscribers("single-topic")
        assert websocket in subscribers

    @pytest.mark.asyncio
    async def test_handle_subscribe_empty_topics_raises_error(self):
        """Test that handle_subscribe raises error for empty topics list."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        await connection_manager.connect(websocket, session_id)

        topics = []

        # Act & Assert
        with pytest.raises(CodebuffError) as exc_info:
            await subscription_handler.handle_subscribe(websocket, topics)

        assert "No topics provided" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_handle_subscribe_unknown_session_raises_error(self):
        """Test that handle_subscribe raises error for unknown session."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)
        websocket = MagicMock()

        # Don't connect the websocket

        topics = ["topic1"]

        # Act & Assert
        with pytest.raises(CodebuffSessionError) as exc_info:
            await subscription_handler.handle_subscribe(websocket, topics)

        assert "Session not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_handle_subscribe_duplicate_topics(self):
        """Test that handle_subscribe handles duplicate topics correctly."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        await connection_manager.connect(websocket, session_id)

        # Subscribe to same topics twice
        topics = ["topic1", "topic2"]
        await subscription_handler.handle_subscribe(websocket, topics)
        await subscription_handler.handle_subscribe(websocket, topics)

        # Assert - should still only have one subscription per topic
        session = await connection_manager.get_session(websocket)
        assert session is not None
        assert len(session.subscriptions) == 2
        for topic in topics:
            assert topic in session.subscriptions

    @pytest.mark.asyncio
    async def test_handle_unsubscribe_removes_subscriptions(self):
        """Test that handle_unsubscribe removes subscriptions from session."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        await connection_manager.connect(websocket, session_id)

        topics = ["topic1", "topic2", "topic3"]

        # Subscribe first
        await subscription_handler.handle_subscribe(websocket, topics)

        # Act - unsubscribe
        await subscription_handler.handle_unsubscribe(websocket, topics)

        # Assert
        session = await connection_manager.get_session(websocket)
        assert session is not None
        for topic in topics:
            assert topic not in session.subscriptions
            subscribers = await connection_manager.get_subscribers(topic)
            assert websocket not in subscribers

    @pytest.mark.asyncio
    async def test_handle_unsubscribe_partial_topics(self):
        """Test that handle_unsubscribe can remove subset of subscriptions."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        await connection_manager.connect(websocket, session_id)

        all_topics = ["topic1", "topic2", "topic3", "topic4"]
        topics_to_unsubscribe = ["topic2", "topic4"]

        # Subscribe to all topics
        await subscription_handler.handle_subscribe(websocket, all_topics)

        # Act - unsubscribe from some topics
        await subscription_handler.handle_unsubscribe(websocket, topics_to_unsubscribe)

        # Assert
        session = await connection_manager.get_session(websocket)
        assert session is not None
        assert "topic1" in session.subscriptions
        assert "topic2" not in session.subscriptions
        assert "topic3" in session.subscriptions
        assert "topic4" not in session.subscriptions

    @pytest.mark.asyncio
    async def test_handle_unsubscribe_empty_topics_raises_error(self):
        """Test that handle_unsubscribe raises error for empty topics list."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        await connection_manager.connect(websocket, session_id)

        topics = []

        # Act & Assert
        with pytest.raises(CodebuffError) as exc_info:
            await subscription_handler.handle_unsubscribe(websocket, topics)

        assert "No topics provided" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_handle_unsubscribe_unknown_session_raises_error(self):
        """Test that handle_unsubscribe raises error for unknown session."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)
        websocket = MagicMock()

        # Don't connect the websocket

        topics = ["topic1"]

        # Act & Assert
        with pytest.raises(CodebuffSessionError) as exc_info:
            await subscription_handler.handle_unsubscribe(websocket, topics)

        assert "Session not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_handle_unsubscribe_non_existent_topics(self):
        """Test that handle_unsubscribe handles non-existent topics gracefully."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        await connection_manager.connect(websocket, session_id)

        # Subscribe to some topics
        subscribed_topics = ["topic1", "topic2"]
        await subscription_handler.handle_subscribe(websocket, subscribed_topics)

        # Act - try to unsubscribe from topics we're not subscribed to
        non_existent_topics = ["topic3", "topic4"]
        await subscription_handler.handle_unsubscribe(websocket, non_existent_topics)

        # Assert - original subscriptions should remain
        session = await connection_manager.get_session(websocket)
        assert session is not None
        assert "topic1" in session.subscriptions
        assert "topic2" in session.subscriptions
        assert "topic3" not in session.subscriptions
        assert "topic4" not in session.subscriptions

    @pytest.mark.asyncio
    async def test_handle_subscribe_multiple_clients_same_topic(self):
        """Test that multiple clients can subscribe to the same topic."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)

        # Create multiple clients
        websocket1 = MagicMock()
        websocket1._test_id = "ws1"
        websocket2 = MagicMock()
        websocket2._test_id = "ws2"
        websocket3 = MagicMock()
        websocket3._test_id = "ws3"

        await connection_manager.connect(websocket1, "session-1")
        await connection_manager.connect(websocket2, "session-2")
        await connection_manager.connect(websocket3, "session-3")

        topic = "shared-topic"

        # Act - all clients subscribe to same topic
        await subscription_handler.handle_subscribe(websocket1, [topic])
        await subscription_handler.handle_subscribe(websocket2, [topic])
        await subscription_handler.handle_subscribe(websocket3, [topic])

        # Assert
        subscribers = await connection_manager.get_subscribers(topic)
        assert len(subscribers) == 3
        assert websocket1 in subscribers
        assert websocket2 in subscribers
        assert websocket3 in subscribers

    @pytest.mark.asyncio
    async def test_handle_subscribe_and_unsubscribe_workflow(self):
        """Test complete subscribe and unsubscribe workflow."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        await connection_manager.connect(websocket, session_id)

        # Act - subscribe to topics
        topics = ["topic1", "topic2", "topic3"]
        await subscription_handler.handle_subscribe(websocket, topics)

        # Verify subscriptions
        session = await connection_manager.get_session(websocket)
        assert len(session.subscriptions) == 3

        # Unsubscribe from some topics
        await subscription_handler.handle_unsubscribe(websocket, ["topic1", "topic3"])

        # Assert - only topic2 should remain
        session = await connection_manager.get_session(websocket)
        assert len(session.subscriptions) == 1
        assert "topic2" in session.subscriptions
        assert "topic1" not in session.subscriptions
        assert "topic3" not in session.subscriptions

    @pytest.mark.asyncio
    async def test_handle_subscribe_with_special_characters_in_topic(self):
        """Test that handle_subscribe works with special characters in topic names."""
        # Arrange
        connection_manager = ConnectionManager()
        subscription_handler = SubscriptionHandler(connection_manager)
        websocket = MagicMock()
        session_id = "test-session-123"

        await connection_manager.connect(websocket, session_id)

        # Topics with special characters
        topics = [
            "topic/with/slashes",
            "topic.with.dots",
            "topic-with-dashes",
            "topic_with_underscores",
        ]

        # Act
        await subscription_handler.handle_subscribe(websocket, topics)

        # Assert
        session = await connection_manager.get_session(websocket)
        assert session is not None
        for topic in topics:
            assert topic in session.subscriptions
