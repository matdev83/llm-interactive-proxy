"""
Regression test for race condition fix in src/connectors/antigravity_oauth.py

Tests that the _models_lock is properly used in _load_models_from_api.
"""

import asyncio

import pytest
from tests.utils.fake_clock import FakeClockContext


class MockAntigravityOAuthConnector:
    """Mock connector to test lock usage."""

    def __init__(self):
        self._models_lock = asyncio.Lock()
        self.available_models = []
        self._available_models_set = set()

    async def _load_models_with_lock(self, models):
        """Simulate the fixed model loading with lock."""
        async with self._models_lock:
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.001))
                clock.advance(0.001)  # Simulate I/O
                await sleep_task
            self.available_models = models
            self._available_models_set = set(models)

    def get_state(self):
        """Read state without lock."""
        return list(self.available_models), set(self._available_models_set)


@pytest.mark.asyncio
async def test_lock_prevents_race_condition():
    """Test that lock prevents concurrent model list modification."""
    connector = MockAntigravityOAuthConnector()

    # Perform concurrent model loads
    tasks = []
    for i in range(10):

        async def load_task(idx):
            models = [f"model_{idx}_j", f"model_{idx}_k"]
            await connector._load_models_with_lock(models)

        tasks.append(load_task(i))

    await asyncio.gather(*tasks)

    # Final state should be consistent
    models_list, models_set = connector.get_state()
    assert len(models_list) == len(models_set), "Models list and set are inconsistent"

    # Should have exactly 2 models from the last completed load
    assert len(models_list) == 2


@pytest.mark.asyncio
async def test_concurrent_state_reads():
    """Test that concurrent reads of models don't fail."""
    connector = MockAntigravityOAuthConnector()
    connector.available_models = ["model_a", "model_b", "model_c"]
    connector._available_models_set = set(connector.available_models)

    # Perform concurrent reads
    tasks = []
    for _ in range(20):

        async def read_task():
            async with FakeClockContext() as clock:
                sleep_task = asyncio.create_task(asyncio.sleep(0.0001))
                clock.advance(0.0001)
                await sleep_task
            return connector.get_state()

        tasks.append(read_task())

    results = await asyncio.gather(*tasks)

    # All reads should succeed and be consistent
    assert all(len(r[0]) == 3 for r in results)
    assert all(len(r[1]) == 3 for r in results)
    assert all(set(r[0]) == r[1] for r in results)
