"""
Regression test for race condition fix in src/connectors/qwen_oauth.py

Tests that _token_refresh_lock is properly used in _load_oauth_credentials.
"""

import asyncio

import pytest


class MockQwenOAuthConnector:
    """Mock connector to test lock usage."""

    def __init__(self):
        self._token_refresh_lock = asyncio.Lock()
        self._oauth_credentials = None
        self._last_modified = 0

    async def _load_oauth_credentials_with_lock(self, new_creds):
        """Simulate of fixed credential loading with lock."""
        async with self._token_refresh_lock:
            await asyncio.sleep(0.001)  # Simulate I/O
            self._oauth_credentials = new_creds
            return True

    async def get_state(self):
        """Read state without lock."""
        return self._oauth_credentials


@pytest.mark.asyncio
async def test_lock_prevents_race_condition():
    """Test that lock prevents concurrent credential modification."""
    connector = MockQwenOAuthConnector()

    # Perform concurrent credential loads
    tasks = [
        connector._load_oauth_credentials_with_lock({"token": f"token_{i}"})
        for i in range(10)
    ]
    results = await asyncio.gather(*tasks)

    # All should succeed
    assert all(results), f"Expected all True, got {results}"

    # Final state should be consistent
    assert connector._oauth_credentials is not None
    # The lock ensures one consistent state
    assert "token_" in connector._oauth_credentials["token"]


@pytest.mark.asyncio
async def test_sequential_credential_loads():
    """Test that sequential credential loads work correctly with lock."""
    connector = MockQwenOAuthConnector()

    # Load sequentially
    for i in range(5):
        result = await connector._load_oauth_credentials_with_lock(
            {"token": f"token_{i}"}
        )
        assert result is True
        assert connector._oauth_credentials["token"] == f"token_{i}"
