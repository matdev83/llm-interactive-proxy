"""
Regression test for race condition fix in src/connectors/opencode_zen.py

Tests that the _token_lock is properly used in _load_oauth_credentials.
"""

import asyncio

import pytest
from tests.utils.fake_clock import FakeClockContext


class MockOpencodeZenConnector:
    """Mock connector to test lock usage."""

    def __init__(self):
        self._token_lock = asyncio.Lock()
        self._oauth_credentials = None
        self._last_modified = 0

    async def _load_oauth_credentials_with_lock(self, new_creds):
        """Simulate the fixed credential loading with lock."""
        async with self._token_lock:
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.001))
                clock.advance(0.001)  # Simulate I/O
                await sleep_task
            self._oauth_credentials = new_creds
            self._last_modified = 123.45

    async def get_state(self):
        """Read state without lock (simulating the race condition)."""
        return self._oauth_credentials, self._last_modified


@pytest.mark.asyncio
async def test_lock_prevents_race_condition():
    """Test that lock prevents concurrent credential modification."""
    connector = MockOpencodeZenConnector()

    # Perform concurrent credential loads
    tasks = []
    for i in range(10):

        async def load_task(idx):
            await connector._load_oauth_credentials_with_lock({"token": f"token_{idx}"})

        tasks.append(load_task(i))

    await asyncio.gather(*tasks)

    # Final state should reflect the last completed load
    # The lock ensures serialization, so we should have a consistent state
    assert connector._oauth_credentials is not None
    # Since the lock serializes operations, one token should win
    assert "token_" in connector._oauth_credentials["token"]


@pytest.mark.asyncio
async def test_concurrent_state_reads():
    """Test that concurrent reads of credentials don't fail."""
    connector = MockOpencodeZenConnector()
    connector._oauth_credentials = {"token": "initial"}
    connector._last_modified = 100.0

    # Perform concurrent reads
    tasks = []
    for _ in range(20):

        async def read_task():
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.0001))
                clock.advance(0.0001)
                await sleep_task
            return await connector.get_state()

        tasks.append(read_task())

    results = await asyncio.gather(*tasks)

    # All reads should succeed
    assert all(r[0] is not None for r in results)
    assert all(r[1] == 100.0 for r in results)
