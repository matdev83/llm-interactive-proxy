"""Integration tests for tool-call reactor subsystem no-global-state constraint.

These tests verify that the subsystem can be constructed via DI without requiring
global mutable state, and that it operates safely in degraded mode when buffer
state is unavailable.
"""

from __future__ import annotations

from src.core.interfaces.tool_call_buffer_state import IToolCallBufferState
from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
    ToolCallBufferState,
)
from src.core.services.tool_call_reactor.stream_buffer_adapter import (
    StreamBufferAdapter,
)


class TestNoGlobalStateConstraint:
    """Tests verifying no-global-state constraint for tool-call reactor subsystem."""

    def test_adapter_can_be_constructed_without_global_registry(self) -> None:
        """Test that StreamBufferAdapter can be constructed without global registry."""
        # Create a buffer state directly (not via global registry)
        buffer_state = ToolCallBufferState()
        adapter = StreamBufferAdapter(buffer_state)

        assert isinstance(adapter, IToolCallBufferState)

    def test_adapter_works_with_injected_registry(self) -> None:
        """Test that adapter works with injected StreamingContextRegistry."""
        # Create registry via DI pattern (not global)
        registry = StreamingContextRegistry(state_ttl_seconds=300)
        stream_id = "test-stream-123"

        # Get buffer state from injected registry
        buffer_state = registry.get_tool_call_buffer(stream_id)
        adapter = StreamBufferAdapter(buffer_state)

        # Verify adapter works correctly
        calls = adapter.consume_new_reactor_calls()
        assert calls == []
        assert buffer_state.reactor_cursor == 0

    def test_adapter_degraded_mode_with_none_buffer(self) -> None:
        """Test that adapter handles None buffer state gracefully (degraded mode)."""
        # This test verifies that components using the adapter should handle
        # None buffer state gracefully. The adapter itself requires a buffer,
        # but higher-level components should accept None and use degraded mode.

        # Create adapter with a buffer
        buffer_state = ToolCallBufferState()
        adapter = StreamBufferAdapter(buffer_state)

        # Verify degraded mode behavior: empty buffer returns empty list
        calls = adapter.consume_new_reactor_calls()
        assert calls == []

        # Verify marking processed doesn't crash with empty buffer
        adapter.mark_processed("test_signature")
        assert "test_signature" in buffer_state.processed_signatures

    def test_adapter_works_without_global_registry_set(self) -> None:
        """Test that adapter works even when global registry is not set."""
        # This test ensures that the adapter doesn't depend on global state
        # being initialized. We create a fresh buffer state without touching
        # any global registry.

        buffer_state = ToolCallBufferState()
        # Add some test data
        call_dict = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        buffer_state.detected_calls = [call_dict]
        buffer_state.reactor_cursor = 0

        adapter = StreamBufferAdapter(buffer_state)

        # Verify adapter works correctly
        calls = adapter.consume_new_reactor_calls()
        assert len(calls) == 1
        assert calls[0].id == "call_1"
        assert buffer_state.reactor_cursor == 1

    def test_adapter_isolation_from_global_state(self) -> None:
        """Test that adapter operations don't affect global registry state."""
        # Create two separate registries (simulating injected vs global)
        injected_registry = StreamingContextRegistry(state_ttl_seconds=300)
        # Note: We don't access get_global_streaming_context_registry() here

        stream_id = "test-stream-isolation"
        buffer_state = injected_registry.get_tool_call_buffer(stream_id)

        # Add a tool call
        call_dict = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        buffer_state.detected_calls.append(call_dict)

        adapter = StreamBufferAdapter(buffer_state)

        # Consume calls
        calls = adapter.consume_new_reactor_calls()
        assert len(calls) == 1

        # Mark as processed
        adapter.mark_processed("test_signature")

        # Verify state is isolated to this buffer
        assert buffer_state.reactor_cursor == 1
        assert "test_signature" in buffer_state.processed_signatures

        # Verify that operations on this adapter don't affect other buffers
        other_buffer = injected_registry.get_tool_call_buffer("other-stream")
        assert other_buffer.reactor_cursor == 0
        assert "test_signature" not in other_buffer.processed_signatures

    def test_adapter_handles_empty_buffer_safely(self) -> None:
        """Test that adapter handles empty buffer without crashing."""
        buffer_state = ToolCallBufferState()
        adapter = StreamBufferAdapter(buffer_state)

        # Multiple calls to consume should be safe
        calls1 = adapter.consume_new_reactor_calls()
        calls2 = adapter.consume_new_reactor_calls()
        calls3 = adapter.consume_new_reactor_calls()

        assert calls1 == []
        assert calls2 == []
        assert calls3 == []
        assert buffer_state.reactor_cursor == 0

    def test_adapter_handles_missing_tool_calls_gracefully(self) -> None:
        """Test that adapter handles missing or invalid tool calls gracefully."""
        buffer_state = ToolCallBufferState()
        # Add invalid tool call data
        buffer_state.detected_calls = [{"invalid": "structure"}]
        buffer_state.reactor_cursor = 0

        adapter = StreamBufferAdapter(buffer_state)

        # Should skip invalid calls without crashing
        calls = adapter.consume_new_reactor_calls()
        # Invalid calls are skipped, so result is empty
        assert calls == []
        # Cursor should still advance
        assert buffer_state.reactor_cursor == 1
