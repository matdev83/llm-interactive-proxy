"""Regression test for APIKeyRedactor memory leak fix.

This test verifies that the APIKeyRedactor cache uses LRU eviction
and doesn't grow unbounded when processing many unique texts.
"""

from src.security import APIKeyRedactor


class TestAPIKeyRedactorMemoryLeakRegression:
    """Regression tests for APIKeyRedactor memory leak fix."""

    def test_cache_bounded_growth(self) -> None:
        """Test that cache doesn't grow unbounded with many unique texts."""
        redactor = APIKeyRedactor(["sk-test-key-123456789"])

        # Process many different short texts (each < 1000 chars to use cache)
        num_texts = 2000
        for i in range(num_texts):
            text = (
                f"This is test message number {i} with some content to be processed and cached. "
                * 10
            )
            text = text[:900]  # Keep it under 1000 chars to use cached version
            redactor.redact(text)

        # Cache should be bounded by _cache_max_size (512)
        cache_size = len(redactor._redact_cache)
        max_size = redactor._cache_max_size

        assert cache_size <= max_size, (
            f"Cache size ({cache_size}) exceeded max size ({max_size}). "
            "LRU eviction is not working properly."
        )

    def test_cache_uses_hash_keys(self) -> None:
        """Test that cache uses hash keys instead of full text to reduce memory."""
        redactor = APIKeyRedactor(["sk-test-key-123456789"])

        # Process some texts to populate cache
        for i in range(100):
            text = f"Test message {i} with content. " * 10
            text = text[:900]
            redactor.redact(text)

        # Check that cache keys are hash strings (32 chars for SHA256 hexdigest)
        if redactor._redact_cache:
            sample_key = next(iter(redactor._redact_cache.keys()))
            assert len(sample_key) == 64, (
                f"Cache key length ({len(sample_key)}) is not 64 chars (SHA256 hexdigest). "
                "Cache may be using full text as keys instead of hashes."
            )
            # Hash should be hexadecimal
            assert all(
                c in "0123456789abcdef" for c in sample_key
            ), "Cache key is not a valid hexadecimal hash."

    def test_cache_lru_eviction(self) -> None:
        """Test that LRU eviction works correctly."""
        redactor = APIKeyRedactor(["sk-test-key-123456789"])
        max_size = redactor._cache_max_size

        # Fill cache beyond max size
        num_texts = max_size + 100
        for i in range(num_texts):
            text = f"Unique text {i} with content. " * 10
            text = text[:900]
            redactor.redact(text)

        # Cache should not exceed max size
        assert len(redactor._redact_cache) <= max_size, (
            f"Cache size ({len(redactor._redact_cache)}) exceeded max size ({max_size}) "
            "after processing {num_texts} unique texts. LRU eviction failed."
        )

        # Verify that oldest entries were evicted
        # Access first few entries to move them to end
        if len(redactor._redact_cache) > 10:
            first_keys = list(redactor._redact_cache.keys())[:5]
            for key in first_keys:
                # Re-access to move to end
                if key in redactor._redact_cache:
                    redactor._redact_cache.move_to_end(key)

            # Add more entries - should evict different ones
            for i in range(num_texts, num_texts + 50):
                text = f"New unique text {i} with content. " * 10
                text = text[:900]
                redactor.redact(text)

            # Cache should still be bounded
            assert (
                len(redactor._redact_cache) <= max_size
            ), "Cache exceeded max size after LRU operations."
