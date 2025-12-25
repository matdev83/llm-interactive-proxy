"""Regression test for race condition in _tiktoken_encoding initialization.

This test ensures that the _tiktoken_encoding global variable is properly
protected against concurrent access to avoid redundant initializations.

GitHub Issue: Token count race condition
File: src/core/utils/token_count.py
"""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from src.core.utils.token_count import count_tokens


class TestTokenCountRaceCondition:
    """Tests for race condition in _tiktoken_encoding lazy initialization."""

    def test_concurrent_threaded_token_count(self):
        """Test that concurrent token counting from threads doesn't cause multiple initializations."""
        # Reset the cached encoding
        import src.core.utils.token_count as tc
        original_encoding = tc._tiktoken_encoding
        tc._tiktoken_encoding = None

        try:
            # Mock tiktoken.get_encoding to track calls
            initialization_count = 0
            original_get_encoding = None

            def mock_get_encoding(name):
                nonlocal initialization_count
                initialization_count += 1
                # Add a small delay to make the race more likely
                import time
                time.sleep(0.001)
                # Return a simple mock that has an encode method
                class MockEncoding:
                    def encode(self, text):
                        return [1, 2, 3, 4, 5]  # Mock encoding

                return MockEncoding()

            # Patch tiktoken.get_encoding
            with patch('tiktoken.get_encoding', side_effect=mock_get_encoding):
                # Test text
                test_text = "Hello world"

                # Create multiple threads that all call count_tokens simultaneously
                num_threads = 20
                with ThreadPoolExecutor(max_workers=num_threads) as executor:
                    futures = [
                        executor.submit(count_tokens, test_text)
                        for _ in range(num_threads)
                    ]

                    results = [f.result() for f in futures]

                # All calls should succeed
                assert all(isinstance(r, int) for r in results)
                assert all(r > 0 for r in results)

                # Only one initialization should have occurred (ideally)
                # Due to the race condition, this may be >1 before the fix
                if initialization_count > 1:
                    pytest.fail(
                        f"Race condition detected: {initialization_count} initializations occurred, "
                        f"expected 1. The _tiktoken_encoding lazy initialization is not properly protected."
                    )

        finally:
            # Restore original encoding
            tc._tiktoken_encoding = original_encoding

    @pytest.mark.asyncio
    async def test_concurrent_async_token_count(self):
        """Test that concurrent token counting from async tasks doesn't cause multiple initializations."""
        # Reset the cached encoding
        import src.core.utils.token_count as tc
        original_encoding = tc._tiktoken_encoding
        tc._tiktoken_encoding = None

        try:
            # Mock tiktoken.get_encoding to track calls
            initialization_count = 0

            def mock_get_encoding(name):
                nonlocal initialization_count
                initialization_count += 1
                # Add a small delay to make the race more likely
                import time
                time.sleep(0.001)
                # Return a simple mock that has an encode method
                class MockEncoding:
                    def encode(self, text):
                        return [1, 2, 3, 4, 5]  # Mock encoding

                return MockEncoding()

            # Patch tiktoken.get_encoding
            with patch('tiktoken.get_encoding', side_effect=mock_get_encoding):
                # Test text
                test_text = "Hello world"

                # Create multiple async tasks that all call count_tokens simultaneously
                num_tasks = 20

                async def async_worker(text):
                    # Run count_tokens in a thread pool to avoid blocking event loop
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(None, count_tokens, text)

                results = await asyncio.gather(
                    *[async_worker(test_text) for _ in range(num_tasks)]
                )

                # All calls should succeed
                assert all(isinstance(r, int) for r in results)
                assert all(r > 0 for r in results)

                # Only one initialization should have occurred (ideally)
                # Due to the race condition, this may be >1 before the fix
                if initialization_count > 1:
                    pytest.fail(
                        f"Race condition detected: {initialization_count} initializations occurred, "
                        f"expected 1. The _tiktoken_encoding lazy initialization is not properly protected."
                    )

        finally:
            # Restore original encoding
            tc._tiktoken_encoding = original_encoding

    def test_token_count_after_initialization(self):
        """Test that token counting works correctly after the encoding is initialized."""
        import src.core.utils.token_count as tc

        # Ensure encoding is initialized
        if tc._tiktoken_encoding is None:
            try:
                tc.count_tokens("test")
            except Exception:
                # If tiktoken is not available, skip this test
                pytest.skip("tiktoken not available")

        # Now count tokens with various inputs
        assert tc.count_tokens("") == 0
        assert tc.count_tokens("Hello") > 0
        assert tc.count_tokens("Hello world") > tc.count_tokens("Hello")
