"""Regression test for VTCBufferState.extracted_tool_calls memory leak fix.

This test verifies that extracted_tool_calls list is properly bounded
when using append_extracted_call method, preventing unbounded memory growth.
"""

import pytest

from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
)


class TestVTCExtractedToolCallsLeakRegression:
    """Regression tests for VTCBufferState extracted_tool_calls memory leak fix."""

    @pytest.fixture
    def registry(self):
        """Create StreamingContextRegistry instance."""
        return StreamingContextRegistry()

    @pytest.fixture
    def vtc_buffer(self, registry: StreamingContextRegistry):
        """Get VTC buffer state for a test stream."""
        stream_id = "test-stream-1"
        return registry.get_vtc_buffer(stream_id)

    def test_extracted_tool_calls_bounded_when_using_append_method(
        self, vtc_buffer
    ) -> None:
        """Test that extracted_tool_calls is bounded when using append_extracted_call."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_EXTRACTED_TOOL_CALLS,
        )

        # Add more tool calls than the limit
        num_calls = _MAX_EXTRACTED_TOOL_CALLS + 500
        for i in range(num_calls):
            tool_call = {
                "id": f"call_{i}",
                "type": "function",
                "function": {
                    "name": f"test_function_{i}",
                    "arguments": '{"arg": "value"}',
                },
            }
            # Use the proper method that enforces limits
            vtc_buffer.append_extracted_call(tool_call)

        # Verify list doesn't exceed max
        final_count = len(vtc_buffer.extracted_tool_calls)
        assert final_count <= _MAX_EXTRACTED_TOOL_CALLS, (
            f"Extracted tool calls count ({final_count}) exceeded max "
            f"({_MAX_EXTRACTED_TOOL_CALLS}). List should be bounded when using "
            "append_extracted_call method."
        )

        # Verify we're at the max (oldest entries were evicted)
        assert final_count == _MAX_EXTRACTED_TOOL_CALLS, (
            f"Final count ({final_count}) should be at max "
            f"({_MAX_EXTRACTED_TOOL_CALLS}) after adding {num_calls} calls. "
            "Oldest entries should be evicted."
        )

    def test_extracted_tool_calls_evicts_oldest_first(
        self, vtc_buffer
    ) -> None:
        """Test that oldest tool calls are evicted first (FIFO eviction)."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_EXTRACTED_TOOL_CALLS,
        )

        # Add tool calls up to limit
        for i in range(_MAX_EXTRACTED_TOOL_CALLS):
            tool_call = {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": f"function_{i}", "arguments": "{}"},
            }
            vtc_buffer.append_extracted_call(tool_call)

        # Verify we're at max
        assert len(vtc_buffer.extracted_tool_calls) == _MAX_EXTRACTED_TOOL_CALLS

        # Record first and last IDs before adding more
        first_id_before = vtc_buffer.extracted_tool_calls[0]["id"]
        last_id_before = vtc_buffer.extracted_tool_calls[-1]["id"]

        # Add more tool calls - should evict oldest
        for i in range(_MAX_EXTRACTED_TOOL_CALLS, _MAX_EXTRACTED_TOOL_CALLS + 100):
            tool_call = {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": f"function_{i}", "arguments": "{}"},
            }
            vtc_buffer.append_extracted_call(tool_call)

        # Verify first ID changed (oldest was evicted)
        first_id_after = vtc_buffer.extracted_tool_calls[0]["id"]
        assert first_id_before != first_id_after, (
            "First tool call ID should have changed after eviction. "
            "Oldest entries should be removed first."
        )

        # Verify last ID is the newest
        last_id_after = vtc_buffer.extracted_tool_calls[-1]["id"]
        assert last_id_after == f"call_{_MAX_EXTRACTED_TOOL_CALLS + 99}", (
            "Last tool call should be the most recently added one."
        )

    def test_extracted_tool_calls_rapid_addition_maintains_limit(
        self, vtc_buffer
    ) -> None:
        """Test that rapid addition of tool calls maintains limit."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_EXTRACTED_TOOL_CALLS,
        )

        # Rapidly add many tool calls
        num_calls = _MAX_EXTRACTED_TOOL_CALLS * 3
        for i in range(num_calls):
            tool_call = {
                "id": f"call_{i}",
                "type": "function",
                "function": {"name": f"function_{i}", "arguments": "{}"},
            }
            vtc_buffer.append_extracted_call(tool_call)

            # Periodically check that limit is maintained
            if i % 100 == 0:
                current_count = len(vtc_buffer.extracted_tool_calls)
                assert current_count <= _MAX_EXTRACTED_TOOL_CALLS, (
                    f"Tool calls count ({current_count}) exceeded max "
                    f"({_MAX_EXTRACTED_TOOL_CALLS}) during rapid addition at iteration {i}."
                )

        # Final check
        final_count = len(vtc_buffer.extracted_tool_calls)
        assert final_count <= _MAX_EXTRACTED_TOOL_CALLS, (
            f"Final count ({final_count}) exceeded max ({_MAX_EXTRACTED_TOOL_CALLS}) "
            "after rapid addition."
        )

    def test_multiple_streams_independent_limits(
        self, registry: StreamingContextRegistry
    ) -> None:
        """Test that multiple streams have independent extracted_tool_calls limits."""
        from src.core.services.streaming.stream_context_registry import (
            _MAX_EXTRACTED_TOOL_CALLS,
        )

        # Create multiple streams
        num_streams = 5
        streams = []
        for i in range(num_streams):
            stream_id = f"stream_{i}"
            buffer = registry.get_vtc_buffer(stream_id)
            streams.append((stream_id, buffer))

        # Add tool calls to each stream
        for stream_id, buffer in streams:
            for j in range(_MAX_EXTRACTED_TOOL_CALLS + 100):
                tool_call = {
                    "id": f"{stream_id}_call_{j}",
                    "type": "function",
                    "function": {"name": f"function_{j}", "arguments": "{}"},
                }
                buffer.append_extracted_call(tool_call)

        # Verify each stream maintains its own limit
        for stream_id, buffer in streams:
            count = len(buffer.extracted_tool_calls)
            assert count <= _MAX_EXTRACTED_TOOL_CALLS, (
                f"Stream {stream_id} has {count} tool calls, exceeding max "
                f"({_MAX_EXTRACTED_TOOL_CALLS}). Each stream should maintain "
                "independent limits."
            )
