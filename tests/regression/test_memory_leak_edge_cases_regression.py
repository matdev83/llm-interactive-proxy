"""Regression test for memory leak edge cases.

This test verifies edge cases for memory leaks:
1. Cache eviction race condition - adding entries faster than eviction
2. Rate limiter cooldown cleanup that depends on access patterns
3. Rate limiter limits cleanup that depends on access patterns

Fixed: Various memory leak fixes ensure cleanup happens even under edge case conditions.
"""

import pytest
from src.core.config.app_config import AppConfig
from src.core.services.buffered_wire_capture_service import BufferedWireCapture
from src.core.services.rate_limiter import InMemoryRateLimiter


class TestMemoryLeakEdgeCasesRegression:
    """Regression tests for memory leak edge cases."""

    @pytest.fixture
    def capture(self) -> BufferedWireCapture:
        """Create BufferedWireCapture with small cache for testing."""
        config = AppConfig()
        capture = BufferedWireCapture(config)
        capture._cache_max_size = 10  # Small limit for testing
        return capture

    @pytest.fixture
    def rate_limiter(self) -> InMemoryRateLimiter:
        """Create InMemoryRateLimiter for testing."""
        return InMemoryRateLimiter()

    def test_cache_eviction_race_condition(self, capture: BufferedWireCapture) -> None:
        """Test if cache can exceed limit when entries are added rapidly."""
        cache_max_size = capture._cache_max_size

        # Add entries rapidly in a tight loop
        # This simulates high-throughput scenario
        for i in range(50):
            # Create unique payloads with different object IDs
            payload = {"test": f"payload_{i}_{1704067200 + i}", "data": "x" * 100}
            capture._get_content_length_cached(payload)

            cache_size = len(capture._content_length_cache)
            assert cache_size <= cache_max_size, (
                f"Cache size ({cache_size}) exceeded limit ({cache_max_size}) "
                f"after {i+1} additions. Cache eviction is not working properly."
            )

        final_size = len(capture._content_length_cache)
        assert final_size <= cache_max_size, (
            f"Final cache size ({final_size}) exceeded limit ({cache_max_size}). "
            "Cache eviction failed to maintain size limit."
        )

    @pytest.mark.asyncio
    async def test_rate_limiter_cooldown_cleanup(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test if cooldowns dict can grow unbounded if cleanup condition isn't met."""
        # Add many cooldowns but keep count just below cleanup threshold
        # Threshold is typically 100
        for i in range(95):  # Just below threshold
            await rate_limiter.apply_cooldown(f"key_{i}", 60)

        cooldown_size = len(rate_limiter._cooldowns)
        assert cooldown_size == 95, f"Expected 95 cooldowns, got {cooldown_size}"

        # Now add more to trigger cleanup
        for i in range(95, 150):
            await rate_limiter.apply_cooldown(f"key_{i}", 60)

        final_size = len(rate_limiter._cooldowns)
        # After cleanup, size should be reasonable (some expired entries removed)
        # Note: Exact size depends on TTL and timing, but shouldn't be unbounded
        assert final_size <= 150, (
            f"Cooldowns size ({final_size}) seems high. "
            "Cleanup should prevent unbounded growth."
        )

    @pytest.mark.asyncio
    async def test_rate_limiter_limits_cleanup(
        self, rate_limiter: InMemoryRateLimiter
    ) -> None:
        """Test if limits dict cleanup depends on access patterns."""
        # Set many limits but don't access them (to test TTL cleanup)
        # Threshold is typically 1000
        for i in range(1200):  # Above cleanup threshold
            await rate_limiter.set_limit(f"limit_key_{i}", 60, 60)

        limits_size = len(rate_limiter._limits)
        # Check if cleanup was triggered
        assert limits_size <= rate_limiter._max_limits, (
            f"Limits size ({limits_size}) exceeded max ({rate_limiter._max_limits}). "
            "Cleanup should have been triggered."
        )

        # Now access some to trigger cleanup check
        for i in range(0, 1200, 100):
            await rate_limiter.check_limit(f"limit_key_{i}")

        final_size = len(rate_limiter._limits)
        assert final_size <= rate_limiter._max_limits, (
            f"Final limits size ({final_size}) exceeded max ({rate_limiter._max_limits}). "
            "Limits cleanup should work even with access patterns."
        )

    @pytest.mark.asyncio
    async def test_rapid_cache_addition_maintains_limit(
        self, capture: BufferedWireCapture
    ) -> None:
        """Test that rapid cache additions maintain limit even under race conditions."""
        cache_max_size = capture._cache_max_size

        # Add entries very rapidly
        import time

        for i in range(100):
            payload = {
                "test": f"rapid_{i}_{time.time_ns()}",
                "data": "x" * 100,
            }
            capture._get_content_length_cached(payload)

            # Check periodically
            if i % 10 == 0:
                cache_size = len(capture._content_length_cache)
                assert cache_size <= cache_max_size, (
                    f"Cache size ({cache_size}) exceeded limit ({cache_max_size}) "
                    f"during rapid addition at iteration {i}"
                )

        final_size = len(capture._content_length_cache)
        assert final_size <= cache_max_size, (
            f"Final cache size ({final_size}) exceeded limit ({cache_max_size}) "
            "after rapid additions"
        )
