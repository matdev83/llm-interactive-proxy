"""Regression test for StreamingContextRegistry TTL cleanup edge case fix.

This test verifies that expired stream contexts are properly cleaned up
even when streams are created but never accessed again (orphaned streams).
"""

import time

import pytest

from src.core.services.streaming.stream_context_registry import StreamingContextRegistry


class TestStreamContextRegistryTTLCleanupRegression:
    """Regression tests for StreamingContextRegistry TTL cleanup edge case fix."""

    def test_ttl_cleanup_triggered_on_access(self) -> None:
        """Test that TTL cleanup is triggered when accessing streams."""
        registry = StreamingContextRegistry(state_ttl_seconds=1)  # Very short TTL for testing

        # Create many streams
        num_streams = 50
        for i in range(num_streams):
            stream_id = f"stream_{i}"
            registry.get_content_state(stream_id)

        initial_size = len(registry._states)
        assert initial_size == num_streams

        # Wait for TTL to expire
        time.sleep(2)

        # Access one stream - this should trigger cleanup
        registry.get_content_state("stream_0")

        # After cleanup, expired states should be removed
        size_after_access = len(registry._states)
        assert size_after_access < initial_size, (
            f"TTL cleanup didn't remove expired states. "
            f"Before access: {initial_size}, After access: {size_after_access}. "
            "Cleanup should be triggered on access."
        )

    def test_orphaned_streams_cleaned_up_by_ttl(self) -> None:
        """Test that orphaned streams (never accessed again) are cleaned up by TTL."""
        registry = StreamingContextRegistry(state_ttl_seconds=1)  # Short TTL for testing

        # Create many streams but only access first few
        num_streams = 100
        for i in range(num_streams):
            stream_id = f"orphan_stream_{i}"
            registry.get_content_state(stream_id)

        # Only access first 10 repeatedly
        for _ in range(10):
            for i in range(10):
                registry.get_content_state(f"orphan_stream_{i}")

        # Wait for TTL to expire
        time.sleep(2)

        # Access one of the frequently accessed streams to trigger cleanup
        registry.get_content_state("orphan_stream_0")

        # Check if orphaned streams (11-100) are cleaned up
        orphaned_count = sum(
            1
            for sid in registry._states.keys()
            if sid.startswith("orphan_stream_") and int(sid.split("_")[-1]) >= 10
        )

        # Orphaned streams should be cleaned up by TTL
        assert orphaned_count == 0, (
            f"Found {orphaned_count} orphaned streams still in registry. "
            "Orphaned streams should be cleaned up by TTL when accessed streams trigger cleanup."
        )

    def test_cleanup_preserves_recently_accessed_streams(self) -> None:
        """Test that recently accessed streams are not cleaned up."""
        registry = StreamingContextRegistry(state_ttl_seconds=2)  # 2 second TTL

        # Create streams
        for i in range(20):
            stream_id = f"stream_{i}"
            registry.get_content_state(stream_id)

        # Access first 5 streams recently
        for i in range(5):
            registry.get_content_state(f"stream_{i}")

        # Wait less than TTL
        time.sleep(1)

        # Access one stream to trigger cleanup
        registry.get_content_state("stream_0")

        # Recently accessed streams should still be present
        for i in range(5):
            assert f"stream_{i}" in registry._states, (
                f"Recently accessed stream stream_{i} was incorrectly cleaned up. "
                "Cleanup should preserve streams that haven't expired."
            )
