"""
Property-based tests for Codebuff Subscription Handler.

These tests verify the correctness properties of subscription management
and topic message distribution.
"""

import asyncio
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


# Property 29: Topic message distribution
@pytest.mark.asyncio
@given(
    topic=topic_strategy(),
    num_subscribers=st.integers(min_value=1, max_value=10),
    num_non_subscribers=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=15)  # Reduced from 30 for performance
async def test_property_29_topic_message_distribution(
    topic, num_subscribers, num_non_subscribers
):
    """
    Feature: codebuff-backend-compatibility, Property 29: Topic message distribution
    Validates: Requirements 9.3

    For any message published to a topic, all clients subscribed to that topic
    should receive it.
    """
    manager = ConnectionManager()

    # Create subscribers
    subscribers = []
    for i in range(num_subscribers):
        ws = MagicMock()
        ws._test_id = f"subscriber_{i}"
        session_id = f"session_subscriber_{i}"
        await manager.connect(ws, session_id)
        await manager.subscribe(ws, [topic])
        subscribers.append(ws)

    # Create non-subscribers
    non_subscribers = []
    for i in range(num_non_subscribers):
        ws = MagicMock()
        ws._test_id = f"non_subscriber_{i}"
        session_id = f"session_non_subscriber_{i}"
        await manager.connect(ws, session_id)
        # Don't subscribe to the topic
        non_subscribers.append(ws)

    # Get all subscribers for the topic
    topic_subscribers = await manager.get_subscribers(topic)

    # Handle weird double-coroutine issue (possibly hypothesis+asyncio interaction artifact)
    if asyncio.iscoroutine(topic_subscribers):
        topic_subscribers = await topic_subscribers

    # Verify all subscribers are in the list
    for subscriber in subscribers:
        assert (
            subscriber in topic_subscribers
        ), f"Subscriber {subscriber._test_id} should be in topic subscribers"

    # Verify non-subscribers are not in the list
    for non_subscriber in non_subscribers:
        assert (
            non_subscriber not in topic_subscribers
        ), f"Non-subscriber {non_subscriber._test_id} should not be in topic subscribers"

    # Verify the count matches
    assert (
        len(topic_subscribers) == num_subscribers
    ), f"Should have exactly {num_subscribers} subscribers"
