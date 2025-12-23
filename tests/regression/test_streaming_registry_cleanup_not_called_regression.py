"""Regression test for StreamingContextRegistry cleanup_expired not called automatically fix.

This test verifies that expired stream contexts are cleaned up even when
cleanup_expired() is not called explicitly, preventing memory leaks when
streams are created but processing stops.
"""

import time

from src.core.services.streaming.stream_context_registry import StreamingContextRegistry


class TestStreamingRegistryCleanupNotCalledRegression:
    """Regression tests for StreamingContextRegistry cleanup_expired not called automatically fix."""

    def test_expired_states_cleaned_up_on_access(self) -> None:
        """Test that expired states are cleaned up when streams are accessed."""
        registry = StreamingContextRegistry(
            state_ttl_seconds=1
        )  # Very short TTL for testing

        # Create many stream states
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
            f"Expired states were not cleaned up. "
            f"Before access: {initial_size}, After access: {size_after_access}. "
            "Cleanup should be triggered on access."
        )

    def test_orphaned_streams_cleaned_up_when_accessed(self) -> None:
        """Test that orphaned streams are cleaned up when any stream is accessed."""
        registry = StreamingContextRegistry(
            state_ttl_seconds=1
        )  # Short TTL for testing

        # Create many streams but never access them again
        num_streams = 100
        for i in range(num_streams):
            stream_id = f"orphan_stream_{i}"
            registry.get_content_state(stream_id)

        initial_size = len(registry._states)
        assert initial_size == num_streams

        # Wait for TTL to expire
        time.sleep(2)

        # Access one stream - this should trigger cleanup of all expired streams
        registry.get_content_state("orphan_stream_0")

        # All expired streams should be cleaned up
        size_after_access = len(registry._states)
        # Should be 1 (the stream we just accessed) or 0 (if it also expired)
        assert size_after_access <= 1, (
            f"Orphaned streams were not cleaned up. "
            f"Before access: {initial_size}, After access: {size_after_access}. "
            "All expired streams should be removed when any stream is accessed."
        )

    def test_manual_cleanup_expired_works(self) -> None:
        """Test that manual cleanup_expired() call works correctly."""
        registry = StreamingContextRegistry(
            state_ttl_seconds=1
        )  # Very short TTL for testing

        # Create stream states
        num_streams = 50
        for i in range(num_streams):
            stream_id = f"stream_{i}"
            registry.get_content_state(stream_id)

        initial_size = len(registry._states)
        assert initial_size == num_streams

        # Wait for TTL to expire
        time.sleep(2)

        # Manually call cleanup_expired()
        registry.cleanup_expired()

        # All expired states should be removed
        size_after_cleanup = len(registry._states)
        assert size_after_cleanup == 0, (
            f"Manual cleanup_expired() did not remove expired states. "
            f"Before cleanup: {initial_size}, After cleanup: {size_after_cleanup}. "
            "All expired states should be removed."
        )

    def test_recently_accessed_streams_not_cleaned_up(self) -> None:
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
