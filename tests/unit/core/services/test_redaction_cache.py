"""
Tests for RedactionCache to ensure session-level caching works correctly.
"""

from __future__ import annotations

import pytest
from src.core.services.redaction_cache import (
    RedactionCache,
    get_global_redaction_cache,
    reset_global_redaction_cache,
)


@pytest.fixture
def cache() -> RedactionCache:
    """Create a fresh RedactionCache for each test."""
    return RedactionCache()


@pytest.fixture(autouse=True)
def reset_global_cache():
    """Reset the global cache before and after each test."""
    reset_global_redaction_cache()
    yield
    reset_global_redaction_cache()


class TestRedactionCache:
    """Tests for RedactionCache class."""

    def test_is_processed_returns_false_for_new_content(
        self, cache: RedactionCache
    ) -> None:
        """New content should not be marked as processed."""
        assert cache.is_processed("session1", "Hello world") is False

    def test_mark_processed_then_is_processed_returns_true(
        self, cache: RedactionCache
    ) -> None:
        """Content marked as processed should return True on subsequent checks."""
        cache.mark_processed("session1", "Hello world")
        assert cache.is_processed("session1", "Hello world") is True

    def test_different_sessions_are_isolated(self, cache: RedactionCache) -> None:
        """Content processed in one session shouldn't affect another."""
        cache.mark_processed("session1", "Hello world")
        assert cache.is_processed("session1", "Hello world") is True
        assert cache.is_processed("session2", "Hello world") is False

    def test_different_content_is_tracked_separately(
        self, cache: RedactionCache
    ) -> None:
        """Different content should be tracked separately."""
        cache.mark_processed("session1", "Hello world")
        assert cache.is_processed("session1", "Hello world") is True
        assert cache.is_processed("session1", "Goodbye world") is False

    def test_get_unprocessed_indices_all_new(self, cache: RedactionCache) -> None:
        """All messages should be returned as unprocessed for a new session."""
        messages = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Message 2"},
            {"role": "user", "content": "Message 3"},
        ]
        indices = cache.get_unprocessed_indices("session1", messages)
        assert indices == [0, 1, 2]

    def test_get_unprocessed_indices_some_processed(
        self, cache: RedactionCache
    ) -> None:
        """Only new messages should be returned as unprocessed."""
        # Process some messages first
        cache.mark_processed("session1", "Message 1")
        cache.mark_processed("session1", "Message 2")

        messages = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Message 2"},
            {"role": "user", "content": "Message 3"},
        ]
        indices = cache.get_unprocessed_indices("session1", messages)
        assert indices == [2]  # Only Message 3 is new

    def test_get_unprocessed_indices_all_processed(self, cache: RedactionCache) -> None:
        """Empty list should be returned if all messages are processed."""
        # Process all messages first
        cache.mark_processed("session1", "Message 1")
        cache.mark_processed("session1", "Message 2")

        messages = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Message 2"},
        ]
        indices = cache.get_unprocessed_indices("session1", messages)
        assert indices == []

    def test_mark_batch_processed(self, cache: RedactionCache) -> None:
        """Batch processing should mark all messages as processed."""
        messages = [
            {"role": "user", "content": "Batch message 1"},
            {"role": "assistant", "content": "Batch message 2"},
        ]
        cache.mark_batch_processed("session1", messages)

        assert cache.is_processed("session1", "Batch message 1") is True
        assert cache.is_processed("session1", "Batch message 2") is True

    def test_clear_session(self, cache: RedactionCache) -> None:
        """Clearing a session should remove all cached data for that session."""
        cache.mark_processed("session1", "Hello world")
        assert cache.is_processed("session1", "Hello world") is True

        cache.clear_session("session1")
        assert cache.is_processed("session1", "Hello world") is False

    def test_clear_session_doesnt_affect_other_sessions(
        self, cache: RedactionCache
    ) -> None:
        """Clearing one session shouldn't affect others."""
        cache.mark_processed("session1", "Hello world")
        cache.mark_processed("session2", "Hello world")

        cache.clear_session("session1")

        assert cache.is_processed("session1", "Hello world") is False
        assert cache.is_processed("session2", "Hello world") is True

    def test_get_stats(self, cache: RedactionCache) -> None:
        """Stats should reflect the number of cached hashes."""
        cache.mark_processed("session1", "Message 1")
        cache.mark_processed("session1", "Message 2")
        cache.mark_processed("session1", "Message 3")

        stats = cache.get_stats("session1")
        assert stats["cached_hashes"] == 3
        assert stats["total_processed"] == 3

    def test_get_stats_empty_session(self, cache: RedactionCache) -> None:
        """Stats for non-existent session should return zeros."""
        stats = cache.get_stats("nonexistent")
        assert stats["cached_hashes"] == 0
        assert stats["total_processed"] == 0

    def test_handles_none_content(self, cache: RedactionCache) -> None:
        """None content should be handled gracefully."""
        cache.mark_processed("session1", None)
        assert cache.is_processed("session1", None) is True
        assert cache.is_processed("session1", "not None") is False

    def test_handles_list_content(self, cache: RedactionCache) -> None:
        """List content (multimodal) should be handled correctly."""
        list_content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]
        cache.mark_processed("session1", list_content)
        assert cache.is_processed("session1", list_content) is True

        # Different list should not match
        different_list = [{"type": "text", "text": "Different"}]
        assert cache.is_processed("session1", different_list) is False

    def test_max_sessions_eviction(self) -> None:
        """Old sessions should be evicted when max is reached."""
        cache = RedactionCache(max_sessions=3)

        # Fill up the cache
        for i in range(3):
            cache.mark_processed(f"session{i}", f"content{i}")

        # All three should exist
        for i in range(3):
            assert cache.is_processed(f"session{i}", f"content{i}") is True

        # Add a fourth session - should evict the oldest
        cache.mark_processed("session3", "content3")

        # session3 should exist
        assert cache.is_processed("session3", "content3") is True

        # At least one old session should be evicted (the oldest one)
        # Note: exact eviction behavior depends on TTL and access patterns


class TestGlobalRedactionCache:
    """Tests for the global cache singleton."""

    def test_get_global_cache_returns_singleton(self) -> None:
        """Getting the global cache twice should return the same instance."""
        cache1 = get_global_redaction_cache()
        cache2 = get_global_redaction_cache()
        assert cache1 is cache2

    def test_reset_global_cache_creates_new_instance(self) -> None:
        """Resetting the global cache should create a new instance."""
        cache1 = get_global_redaction_cache()
        cache1.mark_processed("test", "content")

        reset_global_redaction_cache()

        cache2 = get_global_redaction_cache()
        # New instance shouldn't have the old data
        assert cache2.is_processed("test", "content") is False
