"""Tests for SessionStateStore."""

import asyncio
from unittest.mock import MagicMock

import pytest
from src.services.steering.session_state_store import SessionStateStore


@pytest.fixture
def mock_time():
    """Mock time.monotonic."""
    mock = MagicMock(return_value=1000.0)
    return mock


@pytest.fixture
def store(mock_time):
    """Create a store with mocked time."""
    return SessionStateStore(ttl_seconds=60, max_sessions=5, monotonic=mock_time)


@pytest.mark.asyncio
async def test_set_and_get(store):
    """Test basic set and get operations."""
    await store.set("session1", "key1", "value1")
    assert await store.get("session1", "key1") == "value1"
    assert await store.get("session1", "missing") is None
    assert await store.get("session2", "key1") is None


@pytest.mark.asyncio
async def test_ttl_expiry(store, mock_time):
    """Test that items expire after TTL."""
    await store.set("session1", "key1", "value1")

    # Advance time beyond TTL
    mock_time.return_value = 1061.0

    # Should be expired (lazy eviction)
    assert await store.get("session1", "key1") is None

    # Session should be gone
    assert "session1" not in store._sessions


@pytest.mark.asyncio
async def test_access_updates_ttl(store, mock_time):
    """Test that accessing an item updates its last_seen time."""
    await store.set("session1", "key1", "value1")

    # Advance time within TTL
    mock_time.return_value = 1030.0
    assert await store.get("session1", "key1") == "value1"

    # Advance time such that original set would expire, but update shouldn't
    mock_time.return_value = 1080.0  # 50s after access, 80s after set

    # Should still exist because last_seen was 1030.0, so expires at 1090.0
    assert await store.get("session1", "key1") == "value1"


@pytest.mark.asyncio
async def test_lru_eviction(store, mock_time):
    """Test LRU eviction when max_sessions is exceeded."""
    # Store max_sessions is 5

    # Add 5 sessions at different times
    for i in range(5):
        mock_time.return_value = 1000.0 + i
        await store.set(f"session{i}", "key", "val")

    # session0: 1000.0
    # session1: 1001.0
    # ...
    # session4: 1004.0

    assert len(store._sessions) == 5

    # Add 6th session
    mock_time.return_value = 1005.0
    await store.set("session5", "key", "val")

    # session0 should be evicted (oldest last_seen)
    assert len(store._sessions) == 5
    assert await store.get("session0", "key") is None
    assert await store.get("session5", "key") == "val"


@pytest.mark.asyncio
async def test_concurrent_access():
    """Test concurrent access safety."""
    store = SessionStateStore(ttl_seconds=60, max_sessions=100)

    async def worker(sid):
        for i in range(100):
            await store.set(sid, f"key{i}", i)
            val = await store.get(sid, f"key{i}")
            assert val == i

    # Run multiple workers concurrently
    await asyncio.gather(*[worker(f"s{i}") for i in range(10)])

    assert len(store._sessions) == 10
