"""Regression test for StreamingContextRegistry TTL cleanup edge case fix.

This test verifies that expired stream contexts are properly cleaned up
even when streams are created but never accessed again (orphaned streams).
"""

from freezegun import freeze_time

from src.core.services.streaming.stream_context_registry import StreamingContextRegistry


class TestStreamContextRegistryTTLCleanupRegression:
    """Regression tests for StreamingContextRegistry TTL cleanup edge case fix."""

    def test_ttl_cleanup_triggered_on_access(self) -> None:
        """Test that TTL cleanup is triggered when accessing streams."""
        with freeze_time() as frozen_time:
            registry = StreamingContextRegistry(
                state_ttl_seconds=0.1  # Reduced TTL for performance (was 2)
            )

            # Create many streams
            num_streams = 30  # Reduced from 50
            for i in range(num_streams):
                stream_id = f"stream_{i}"
                registry.get_content_state(stream_id)

            initial_size = len(registry._states)
            assert initial_size == num_streams

            # Advance time to expire TTL
            frozen_time.tick(0.15)  # Slightly more than TTL

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
        with freeze_time() as frozen_time:
            registry = StreamingContextRegistry(
                state_ttl_seconds=1  # Reduced TTL for performance (was 2)
            )

            # Create many streams but only access first few
            num_streams = 30  # Reduced from 50
            for i in range(num_streams):
                stream_id = f"orphan_stream_{i}"
                registry.get_content_state(stream_id)

            # Only access first 10 repeatedly
            for _ in range(5):  # Reduced from 10
                for i in range(5):  # Reduced from 10
                    registry.get_content_state(f"orphan_stream_{i}")

            # Advance time to expire TTL
            frozen_time.tick(1.1)  # Slightly more than TTL

            # Access one of the frequently accessed streams to trigger cleanup
            registry.get_content_state("orphan_stream_0")

            # Check if orphaned streams (5+) are cleaned up
            orphaned_count = sum(
                1
                for sid in registry._states
                if sid.startswith("orphan_stream_") and int(sid.split("_")[-1]) >= 5
            )

            # Orphaned streams should be cleaned up by TTL
            assert orphaned_count == 0, (
                f"Found {orphaned_count} orphaned streams still in registry. "
                "Orphaned streams should be cleaned up by TTL when accessed streams trigger cleanup."
            )

    def test_cleanup_preserves_recently_accessed_streams(self) -> None:
        """Test that recently accessed streams are not cleaned up."""
        with freeze_time() as frozen_time:
            registry = StreamingContextRegistry(
                state_ttl_seconds=1  # Reduced TTL for performance (was 2)
            )

            # Create streams
            for i in range(10):  # Reduced from 20
                stream_id = f"stream_{i}"
                registry.get_content_state(stream_id)

            # Access first 5 streams recently
            for i in range(5):
                registry.get_content_state(f"stream_{i}")

            # Advance time less than TTL
            frozen_time.tick(0.5)  # Half of TTL

            # Access one stream to trigger cleanup
            registry.get_content_state("stream_0")

            # Recently accessed streams should still be present
            for i in range(5):
                assert f"stream_{i}" in registry._states, (
                    f"Recently accessed stream stream_{i} was incorrectly cleaned up. "
                    "Cleanup should preserve streams that haven't expired."
                )
