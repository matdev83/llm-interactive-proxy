"""
Property-based tests for Codebuff Connection Manager.

These tests verify the correctness properties of connection management,
session tracking, and subscription handling.
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from src.codebuff.connection_manager import ConnectionManager


# Test strategies
@st.composite
def session_id_strategy(draw):
    """Generate valid session IDs."""
    return draw(st.text(min_size=1, max_size=100))


@st.composite
def topic_strategy(draw):
    """Generate valid topic names."""
    return draw(st.text(min_size=1, max_size=50))


@st.composite
def websocket_strategy(draw):
    """Generate mock WebSocket objects."""
    ws = MagicMock()
    # Give each websocket a unique ID for tracking
    ws._test_id = draw(st.integers(min_value=0, max_value=1000000))
    return ws


# Property 1: Connection tracking
@given(session_id=session_id_strategy())
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_property_1_connection_tracking(session_id):
    """
    Feature: codebuff-backend-compatibility, Property 1: Connection tracking
    Validates: Requirements 1.1

    For any WebSocket connection to /ws, the system should create a session
    entry and track the connection.
    """
    manager = ConnectionManager()
    websocket = MagicMock()

    # Connect the websocket
    await manager.connect(websocket, session_id)

    # Verify the connection is tracked
    session = await manager.get_session(websocket)
    assert session is not None, "Session should be created for connection"
    assert session.session_id == session_id, "Session ID should match"
    assert isinstance(session.created_at, datetime), "Created timestamp should be set"
    assert isinstance(session.last_seen, datetime), "Last seen timestamp should be set"


# Property 2: Session ID association
@given(session_id=session_id_strategy())
@settings(max_examples=30)  # Reduced from 50 for performance
@pytest.mark.asyncio
async def test_property_2_session_id_association(session_id):
    """
    Feature: codebuff-backend-compatibility, Property 2: Session ID association
    Validates: Requirements 1.2

    For any identify message with a session ID, the system should store that ID
    and associate it with the WebSocket connection.
    """
    manager = ConnectionManager()
    websocket = MagicMock()

    # Connect with the session ID
    await manager.connect(websocket, session_id)

    # Verify the session ID is stored and associated
    session = await manager.get_session(websocket)
    assert session is not None, "Session should exist"
    assert session.session_id == session_id, "Session ID should be stored correctly"


# Property 3: Heartbeat timestamp updates
@given(session_id=session_id_strategy())
@settings(max_examples=30, deadline=None)
@pytest.mark.asyncio
async def test_property_3_heartbeat_timestamp_updates(session_id):
    """
    Feature: codebuff-backend-compatibility, Property 3: Heartbeat timestamp updates
    Validates: Requirements 1.3

    For any ping message from a connection, the system should update the
    last-seen timestamp for that connection.
    """
    manager = ConnectionManager()
    websocket = MagicMock()

    # Connect and get initial timestamp
    await manager.connect(websocket, session_id)
    session = await manager.get_session(websocket)
    initial_last_seen = session.last_seen

    # Update last seen (simulating a ping)
    await manager.update_last_seen(websocket)

    # Verify timestamp was updated
    session = await manager.get_session(websocket)
    assert (
        session.last_seen > initial_last_seen
    ), "Last seen timestamp should be updated"


# Property 4: Session cleanup on disconnect
@given(session_id=session_id_strategy())
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_property_4_session_cleanup_on_disconnect(session_id):
    """
    Feature: codebuff-backend-compatibility, Property 4: Session cleanup on disconnect
    Validates: Requirements 1.5

    For any disconnecting client, the system should remove the session state
    and connection from tracking.
    """
    manager = ConnectionManager()
    websocket = MagicMock()

    # Connect
    await manager.connect(websocket, session_id)
    session_check = await manager.get_session(websocket)
    assert session_check is not None, "Session should exist"

    # Disconnect
    await manager.disconnect(websocket)

    # Verify session is removed
    session = await manager.get_session(websocket)
    assert session is None, "Session should be removed after disconnect"


# Property 27: Subscription addition
@given(
    session_id=session_id_strategy(),
    topics=st.lists(topic_strategy(), min_size=1, max_size=10, unique=True),
)
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_property_27_subscription_addition(session_id, topics):
    """
    Feature: codebuff-backend-compatibility, Property 27: Subscription addition
    Validates: Requirements 9.1

    For any subscribe action with topics, the system should add the client
    to those topics.
    """
    manager = ConnectionManager()
    websocket = MagicMock()

    # Connect
    await manager.connect(websocket, session_id)

    # Subscribe to topics
    await manager.subscribe(websocket, topics)

    # Verify subscriptions were added
    session = await manager.get_session(websocket)
    assert session is not None, "Session should exist"
    for topic in topics:
        assert topic in session.subscriptions, f"Should be subscribed to {topic}"
        subscribers = await manager.get_subscribers(topic)
        assert websocket in subscribers, f"Should be in subscribers list for {topic}"


# Property 28: Subscription removal
@given(
    session_id=session_id_strategy(),
    topics=st.lists(topic_strategy(), min_size=1, max_size=10, unique=True),
)
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_property_28_subscription_removal(session_id, topics):
    """
    Feature: codebuff-backend-compatibility, Property 28: Subscription removal
    Validates: Requirements 9.2

    For any unsubscribe action with topics, the system should remove the client
    from those topics.
    """
    manager = ConnectionManager()
    websocket = MagicMock()

    # Connect and subscribe
    await manager.connect(websocket, session_id)
    await manager.subscribe(websocket, topics)

    # Verify subscriptions exist
    session = await manager.get_session(websocket)
    for topic in topics:
        assert topic in session.subscriptions

    # Unsubscribe from topics
    await manager.unsubscribe(websocket, topics)

    # Verify subscriptions were removed
    session = await manager.get_session(websocket)
    for topic in topics:
        assert (
            topic not in session.subscriptions
        ), f"Should not be subscribed to {topic}"
        subscribers = await manager.get_subscribers(topic)
        assert (
            websocket not in subscribers
        ), f"Should not be in subscribers list for {topic}"


# Property 30: Subscription cleanup
@given(
    session_id=session_id_strategy(),
    topics=st.lists(topic_strategy(), min_size=1, max_size=10, unique=True),
)
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_property_30_subscription_cleanup(session_id, topics):
    """
    Feature: codebuff-backend-compatibility, Property 30: Subscription cleanup
    Validates: Requirements 9.4

    For any disconnecting client, all subscriptions for that client should
    be removed.
    """
    manager = ConnectionManager()
    websocket = MagicMock()

    # Connect and subscribe
    await manager.connect(websocket, session_id)
    await manager.subscribe(websocket, topics)

    # Verify subscriptions exist
    for topic in topics:
        subscribers = await manager.get_subscribers(topic)
        assert websocket in subscribers

    # Disconnect
    await manager.disconnect(websocket)

    # Verify all subscriptions were cleaned up
    for topic in topics:
        subscribers = await manager.get_subscribers(topic)
        assert (
            websocket not in subscribers
        ), f"Should not be in subscribers list for {topic} after disconnect"
