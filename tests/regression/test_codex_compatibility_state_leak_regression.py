"""Regression test for Codex compatibility state memory leak fix.

This test verifies that CompatibilityState caches (droid_tool_name_cache and
droid_tool_args_buffer) are properly cleared when cleanup_state is called,
preventing memory leaks when states are not properly released.
"""

import pytest
from src.connectors.openai_codex.compat import CompatibilityLayer


class TestCodexCompatibilityStateLeakRegression:
    """Regression tests for CompatibilityState memory leak fix."""

    @pytest.mark.asyncio
    async def test_state_caches_cleared_on_cleanup(self) -> None:
        """Test that state caches are cleared when cleanup_state is called."""
        layer = CompatibilityLayer()
        state = layer.create_state()

        # Populate caches
        state.droid_tool_name_cache["call_1"] = "tool_1"
        state.droid_tool_name_cache["call_2"] = "tool_2"
        state.droid_tool_args_buffer["call_1"] = '{"arg": 1}'
        state.droid_tool_args_buffer["call_2"] = '{"arg": 2}'

        assert len(state.droid_tool_name_cache) == 2
        assert len(state.droid_tool_args_buffer) == 2

        # Cleanup should clear caches
        await layer.cleanup_state(state)

        assert state.droid_tool_name_cache == {}
        assert state.droid_tool_args_buffer == {}
        assert len(state.droid_tool_name_cache) == 0
        assert len(state.droid_tool_args_buffer) == 0

    @pytest.mark.asyncio
    async def test_multiple_states_dont_leak_when_cleaned(self) -> None:
        """Test that multiple states can be created and cleaned without leaking."""
        layer = CompatibilityLayer()

        # Create and populate many states
        num_states = 100
        states = []
        for i in range(num_states):
            state = layer.create_state()
            # Simulate tool calls
            for j in range(10):
                tc_id = f"call_{i}_{j}"
                state.droid_tool_name_cache[tc_id] = f"tool_{j}"
                state.droid_tool_args_buffer[tc_id] = f'{{"arg": {j}}}'
            states.append(state)

        # Verify all states have populated caches
        for state in states:
            assert len(state.droid_tool_name_cache) == 10
            assert len(state.droid_tool_args_buffer) == 10

        # Cleanup all states
        for state in states:
            await layer.cleanup_state(state)

        # Verify all caches are cleared
        for state in states:
            assert state.droid_tool_name_cache == {}
            assert state.droid_tool_args_buffer == {}

    @pytest.mark.asyncio
    async def test_state_caches_remain_empty_after_cleanup(self) -> None:
        """Test that cleaned state caches remain empty even if accessed again."""
        layer = CompatibilityLayer()
        state = layer.create_state()

        # Populate and cleanup
        state.droid_tool_name_cache["call_1"] = "tool_1"
        state.droid_tool_args_buffer["call_1"] = '{"arg": 1}'
        await layer.cleanup_state(state)

        # Verify caches are empty
        assert state.droid_tool_name_cache == {}
        assert state.droid_tool_args_buffer == {}

        # Try to access caches again - should still be empty
        assert "call_1" not in state.droid_tool_name_cache
        assert "call_1" not in state.droid_tool_args_buffer

        # Verify flags are reset
        assert state.is_kilocode is False
        assert state.is_droid is False
        assert state.pending_tool_calls == []
