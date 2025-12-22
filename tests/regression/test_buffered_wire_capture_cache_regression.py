"""Regression test for BufferedWireCapture cache memory leak fix.

This test verifies that _content_length_cache doesn't grow unbounded
when entries are added rapidly and that cache eviction works correctly.
"""

import pytest

from src.core.config.app_config import AppConfig
from src.core.services.buffered_wire_capture_service import BufferedWireCapture


class TestBufferedWireCaptureCacheRegression:
    """Regression tests for BufferedWireCapture cache memory leak fix."""

    def test_cache_bounded_growth(self) -> None:
        """Test that cache doesn't grow unbounded when entries are added rapidly."""
        config = AppConfig()
        capture = BufferedWireCapture(config)
        original_cache_max_size = capture._cache_max_size
        capture._cache_max_size = 100  # Small limit for testing

        try:
            # Simulate rapid addition of unique payloads
            # Each payload gets a new object id, so cache will grow
            num_payloads = 200
            for i in range(num_payloads):
                payload = {"test": f"payload_{i}", "data": "x" * 100}
                capture._get_content_length_cached(payload)

                # Check periodically if cache exceeded limit
                cache_size = len(capture._content_length_cache)
                assert cache_size <= capture._cache_max_size, (
                    f"Cache size ({cache_size}) exceeded max size ({capture._cache_max_size}) "
                    f"after {i+1} additions. Cache eviction is not working properly."
                )

            # Final check
            final_size = len(capture._content_length_cache)
            assert final_size <= capture._cache_max_size, (
                f"Final cache size ({final_size}) exceeds max size ({capture._cache_max_size}). "
                "Cache eviction failed to maintain size limit."
            )
        finally:
            # Restore original cache size
            capture._cache_max_size = original_cache_max_size

    def test_cache_eviction_removes_oldest_entries(self) -> None:
        """Test that cache eviction removes oldest entries when limit is reached."""
        config = AppConfig()
        capture = BufferedWireCapture(config)
        original_cache_max_size = capture._cache_max_size
        capture._cache_max_size = 5  # Very small limit for testing

        try:
            # Add entries up to limit
            payloads = []
            for i in range(5):
                payload = {"test": f"payload_{i}"}
                payloads.append(payload)
                capture._get_content_length_cached(payload)

            assert len(capture._content_length_cache) == 5

            # Store first payload ID to verify it gets evicted
            first_payload_id = id(payloads[0])

            # Add more entries - should evict oldest
            for i in range(5, 10):
                payload = {"test": f"payload_{i}"}
                capture._get_content_length_cached(payload)

            # Cache should still be at max size
            assert len(capture._content_length_cache) <= capture._cache_max_size, (
                f"Cache size ({len(capture._content_length_cache)}) exceeded max "
                f"({capture._cache_max_size}) after eviction."
            )

            # First payload should be evicted
            assert first_payload_id not in capture._content_length_cache, (
                "Oldest cache entry was not evicted. "
                "Cache eviction should remove oldest entries when limit is reached."
            )
        finally:
            # Restore original cache size
            capture._cache_max_size = original_cache_max_size

    def test_cache_reuses_entries_for_same_object(self) -> None:
        """Test that cache reuses entries for the same payload object."""
        config = AppConfig()
        capture = BufferedWireCapture(config)

        # Create a payload and reuse it
        payload = {"test": "reused_payload", "data": "x" * 100}

        # Add same payload multiple times
        for _ in range(10):
            capture._get_content_length_cached(payload)

        # Cache should only have one entry (same object ID)
        assert len(capture._content_length_cache) == 1, (
            f"Cache should have 1 entry for reused payload, "
            f"but has {len(capture._content_length_cache)}. "
            "Cache should reuse entries for the same object."
        )

        # Verify the entry exists
        payload_id = id(payload)
        assert payload_id in capture._content_length_cache, (
            "Cache entry for reused payload not found. "
            "Cache should maintain entries for reused objects."
        )
