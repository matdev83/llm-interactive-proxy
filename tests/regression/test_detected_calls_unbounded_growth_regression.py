"""Regression test for detected_calls unbounded growth fix.

This test verifies that ToolCallBufferState.detected_calls list is properly
bounded to prevent unbounded memory growth when many tool calls are detected.
"""

import pytest

from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
)


class TestDetectedCallsUnboundedGrowthRegression:
    """Regression tests for detected_calls unbounded growth fix."""

    def test_detected_calls_bounded_by_max_limit(self) -> None:
        """Test that detected_calls list doesn't exceed MAX_DETECTED_TOOL_CALLS limit."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_DETECTED_TOOL_CALLS,
        )

        registry = StreamingContextRegistry()
        stream_id = "test-stream-1"

        # Get tool call buffer state
        state = registry.get_tool_call_buffer(stream_id)

        # Try to add more than the limit
        num_calls = _MAX_DETECTED_TOOL_CALLS + 500

        for i in range(num_calls):
            tool_call = {
                "id": f"call_{i}",
                "type": "function",
                "function": {
                    "name": f"test_function_{i}",
                    "arguments": '{"arg": "value"}',
                },
            }
            state.append_detected_call(tool_call)

        # List length should not exceed max limit
        assert len(state.detected_calls) <= _MAX_DETECTED_TOOL_CALLS, (
            f"Detected calls count ({len(state.detected_calls)}) exceeded max limit "
            f"({_MAX_DETECTED_TOOL_CALLS}). Eviction is not working."
        )

    def test_detected_calls_evicts_oldest_when_limit_reached(self) -> None:
        """Test that oldest detected calls are evicted when limit is reached."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_DETECTED_TOOL_CALLS,
        )

        registry = StreamingContextRegistry()
        stream_id = "test-stream-2"
        state = registry.get_tool_call_buffer(stream_id)

        # Add calls up to limit
        for i in range(_MAX_DETECTED_TOOL_CALLS):
            tool_call = {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": f"func_{i}", "arguments": "{}"},
            }
            state.append_detected_call(tool_call)

        assert len(state.detected_calls) == _MAX_DETECTED_TOOL_CALLS

        # Store first call ID to verify it gets evicted
        first_call_id = state.detected_calls[0]["id"]

        # Add more calls - should evict oldest
        for i in range(_MAX_DETECTED_TOOL_CALLS, _MAX_DETECTED_TOOL_CALLS + 10):
            tool_call = {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": f"func_{i}", "arguments": "{}"},
            }
            state.append_detected_call(tool_call)

        # Should still be at max limit
        assert len(state.detected_calls) <= _MAX_DETECTED_TOOL_CALLS, (
            "Detected calls exceeded max limit after adding more calls."
        )

        # First call should be evicted
        assert state.detected_calls[0]["id"] != first_call_id, (
            "Oldest detected call was not evicted."
        )

    def test_detected_calls_handles_many_tool_calls(self) -> None:
        """Test that detected_calls handles many tool calls without memory leak."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_DETECTED_TOOL_CALLS,
        )

        registry = StreamingContextRegistry()
        stream_id = "test-stream-many-calls"
        state = registry.get_tool_call_buffer(stream_id)

        # Simulate many tool calls (100k)
        num_calls = 100000

        for i in range(num_calls):
            tool_call = {
                "id": f"call_{i}",
                "type": "function",
                "function": {
                    "name": f"test_function_{i}",
                    "arguments": '{"arg": "value"}',
                },
            }
            state.append_detected_call(tool_call)

            # Verify bounded growth periodically
            if (i + 1) % 10000 == 0:
                assert len(state.detected_calls) <= _MAX_DETECTED_TOOL_CALLS, (
                    f"Detected calls grew unbounded at iteration {i + 1}. "
                    f"Count: {len(state.detected_calls)}, max: {_MAX_DETECTED_TOOL_CALLS}"
                )

        # Final check
        assert len(state.detected_calls) <= _MAX_DETECTED_TOOL_CALLS, (
            f"Final detected calls count ({len(state.detected_calls)}) "
            f"exceeded max limit ({_MAX_DETECTED_TOOL_CALLS}) after many calls."
        )

    def test_detected_calls_uses_append_method(self) -> None:
        """Test that append_detected_call method enforces limits."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_DETECTED_TOOL_CALLS,
        )

        registry = StreamingContextRegistry()
        stream_id = "test-stream-append"
        state = registry.get_tool_call_buffer(stream_id)

        # Verify append_detected_call method exists
        assert hasattr(state, "append_detected_call"), (
            "append_detected_call method is missing. "
            "Direct append would bypass size limits."
        )

        # Use the method to add calls
        for i in range(_MAX_DETECTED_TOOL_CALLS + 100):
            tool_call = {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": f"func_{i}", "arguments": "{}"},
            }
            state.append_detected_call(tool_call)

        # Should be bounded
        assert len(state.detected_calls) <= _MAX_DETECTED_TOOL_CALLS, (
            "append_detected_call method is not enforcing size limits."
        )
