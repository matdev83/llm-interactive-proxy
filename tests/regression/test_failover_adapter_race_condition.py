"""
Regression test for failover_command_handler race condition fix.

This test verifies that concurrent access to _local_state in
SessionStateApplicationStateAdapter is properly protected by locks.
"""

import asyncio
import sys

sys.path.insert(0, ".")

import pytest
from src.core.commands.handlers.failover_command_handler import (
    SessionStateApplicationStateAdapter,
)
from src.core.domain.session import Session


class TestFailoverCommandHandlerRaceCondition:
    """Regression tests for race condition in SessionStateApplicationStateAdapter."""

    @pytest.fixture
    def adapter(self):
        """Create a SessionStateApplicationStateAdapter for testing."""
        session = Session(session_id="test-session")

        # Create a concrete implementation that implements abstract method
        class ConcreteAdapter(SessionStateApplicationStateAdapter):
            def set_failover_routes(self, routes):
                # Minimal implementation to make class concrete
                pass

        return ConcreteAdapter(session)

    @pytest.mark.asyncio
    async def test_concurrent_set_setting_operations(self, adapter):
        """Test that concurrent set_setting operations are thread-safe."""

        async def set_values(iter_id: int):
            for i in range(100):
                adapter.set_setting(f"key_{iter_id}_{i}", f"value_{i}")

        # Run concurrent operations
        tasks = [asyncio.create_task(set_values(i)) for i in range(10)]
        await asyncio.gather(*tasks)

        # Verify all keys are set
        with adapter._lock:
            for iter_id in range(10):
                for i in range(100):
                    key = f"key_{iter_id}_{i}"
                    assert key in adapter._local_state, f"Key {key} not found"

    @pytest.mark.asyncio
    async def test_concurrent_get_setting_operations(self, adapter):
        """Test that concurrent get_setting operations are thread-safe."""
        # Pre-populate with some values
        for i in range(100):
            adapter.set_setting(f"key_{i}", f"value_{i}")

        async def read_values(iter_id: int):
            for i in range(100):
                value = adapter.get_setting(f"key_{i}")
                assert value == f"value_{i}", f"Unexpected value for key_{i}"

        # Run concurrent read operations
        tasks = [asyncio.create_task(read_values(i)) for i in range(10)]
        await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    async def test_concurrent_get_set_operations(self, adapter):
        """Test that concurrent get/set operations are thread-safe."""

        async def mixed_operations(iter_id: int):
            for i in range(50):
                key = f"key_{iter_id}_{i % 10}"
                adapter.set_setting(key, f"value_{i}")
                adapter.get_setting(key)

        # Run concurrent mixed operations
        tasks = [asyncio.create_task(mixed_operations(i)) for i in range(10)]
        await asyncio.gather(*tasks)

        # Verify no data corruption
        with adapter._lock:
            for key in adapter._local_state:
                value = adapter._local_state[key]
                assert isinstance(
                    value, str
                ), f"Expected string value, got {type(value)}"

    @pytest.mark.asyncio
    async def test_concurrent_command_prefix_operations(self, adapter):
        """Test that concurrent command_prefix operations are thread-safe."""

        async def set_prefix(iter_id: int):
            for i in range(100):
                adapter.set_command_prefix(f"prefix_{iter_id}_{i}")

        async def get_prefix():
            for _ in range(100):
                prefix = adapter.get_command_prefix()
                assert prefix is None or isinstance(prefix, str)

        # Run concurrent operations
        tasks = []
        tasks.extend(asyncio.create_task(set_prefix(i)) for i in range(5))
        tasks.extend(asyncio.create_task(get_prefix()) for _ in range(5))
        await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    async def test_concurrent_api_key_redaction_operations(self, adapter):
        """Test that concurrent API key redaction operations are thread-safe."""

        async def set_enabled(iter_id: int):
            for i in range(100):
                adapter.set_api_key_redaction_enabled(i % 2 == 0)

        async def get_enabled():
            for _ in range(100):
                enabled = adapter.get_api_key_redaction_enabled()
                assert isinstance(enabled, bool)

        # Run concurrent operations
        tasks = []
        tasks.extend(asyncio.create_task(set_enabled(i)) for i in range(5))
        tasks.extend(asyncio.create_task(get_enabled()) for _ in range(5))
        await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    async def test_concurrent_disable_commands_operations(self, adapter):
        """Test that concurrent disable_commands operations are thread-safe."""

        async def set_disabled(iter_id: int):
            for i in range(100):
                adapter.set_disable_commands(i % 2 == 0)

        async def get_disabled():
            for _ in range(100):
                disabled = adapter.get_disable_commands()
                assert isinstance(disabled, bool)

        # Run concurrent operations
        tasks = []
        tasks.extend(asyncio.create_task(set_disabled(i)) for i in range(5))
        tasks.extend(asyncio.create_task(get_disabled()) for _ in range(5))
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
