"""Tests for StreamBufferAdapter."""

from __future__ import annotations

from src.core.domain.chat import FunctionCall, ToolCall
from src.core.interfaces.tool_call_buffer_state import IToolCallBufferState
from src.core.services.streaming.stream_context_registry import ToolCallBufferState
from src.core.services.tool_call_reactor.stream_buffer_adapter import (
    StreamBufferAdapter,
)


class TestStreamBufferAdapter:
    """Tests for StreamBufferAdapter."""

    def test_adapter_implements_interface(self) -> None:
        """Test that adapter implements IToolCallBufferState interface."""
        buffer_state = ToolCallBufferState()
        adapter = StreamBufferAdapter(buffer_state)
        assert isinstance(adapter, IToolCallBufferState)

    def test_consume_new_reactor_calls_empty_buffer(self) -> None:
        """Test consuming from empty buffer returns empty list."""
        buffer_state = ToolCallBufferState()
        adapter = StreamBufferAdapter(buffer_state)
        calls = adapter.consume_new_reactor_calls()
        assert calls == []
        assert buffer_state.reactor_cursor == 0

    def test_consume_new_reactor_calls_advances_cursor(self) -> None:
        """Test that consuming calls advances reactor_cursor correctly."""
        buffer_state = ToolCallBufferState()
        # Add some detected calls
        call1 = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        call2 = {
            "id": "call_2",
            "type": "function",
            "function": {"name": "test_tool2", "arguments": '{"key2": "value2"}'},
        }
        buffer_state.detected_calls = [call1, call2]
        buffer_state.reactor_cursor = 0

        adapter = StreamBufferAdapter(buffer_state)
        calls = adapter.consume_new_reactor_calls()

        # Should return both calls
        assert len(calls) == 2
        assert buffer_state.reactor_cursor == 2

    def test_consume_new_reactor_calls_partial_consumption(self) -> None:
        """Test consuming when cursor is already partway through."""
        buffer_state = ToolCallBufferState()
        call1 = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        call2 = {
            "id": "call_2",
            "type": "function",
            "function": {"name": "test_tool2", "arguments": '{"key2": "value2"}'},
        }
        buffer_state.detected_calls = [call1, call2]
        buffer_state.reactor_cursor = 1  # Already consumed first call

        adapter = StreamBufferAdapter(buffer_state)
        calls = adapter.consume_new_reactor_calls()

        # Should return only the second call
        assert len(calls) == 1
        assert calls[0].id == "call_2"
        assert buffer_state.reactor_cursor == 2

    def test_consume_new_reactor_calls_all_consumed(self) -> None:
        """Test consuming when all calls already consumed."""
        buffer_state = ToolCallBufferState()
        call1 = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        buffer_state.detected_calls = [call1]
        buffer_state.reactor_cursor = 1  # Already consumed

        adapter = StreamBufferAdapter(buffer_state)
        calls = adapter.consume_new_reactor_calls()

        # Should return empty list
        assert calls == []
        assert buffer_state.reactor_cursor == 1

    def test_consume_new_reactor_calls_converts_to_toolcall(self) -> None:
        """Test that dict tool calls are converted to ToolCall domain models."""
        buffer_state = ToolCallBufferState()
        call_dict = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        buffer_state.detected_calls = [call_dict]
        buffer_state.reactor_cursor = 0

        adapter = StreamBufferAdapter(buffer_state)
        calls = adapter.consume_new_reactor_calls()

        assert len(calls) == 1
        assert isinstance(calls[0], ToolCall)
        assert calls[0].id == "call_1"
        assert calls[0].function.name == "test_tool"

    def test_consume_new_reactor_calls_already_toolcall(self) -> None:
        """Test that ToolCall objects are passed through unchanged."""
        buffer_state = ToolCallBufferState()
        tool_call = ToolCall(
            id="call_1",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )
        buffer_state.detected_calls = [tool_call]
        buffer_state.reactor_cursor = 0

        adapter = StreamBufferAdapter(buffer_state)
        calls = adapter.consume_new_reactor_calls()

        assert len(calls) == 1
        assert calls[0] is tool_call  # Should be same object

    def test_mark_processed_adds_signature(self) -> None:
        """Test that mark_processed adds signature to processed_signatures."""
        buffer_state = ToolCallBufferState()
        adapter = StreamBufferAdapter(buffer_state)

        assert "signature_1" not in buffer_state.processed_signatures
        adapter.mark_processed("signature_1")
        assert "signature_1" in buffer_state.processed_signatures

    def test_mark_processed_multiple_signatures(self) -> None:
        """Test marking multiple signatures."""
        buffer_state = ToolCallBufferState()
        adapter = StreamBufferAdapter(buffer_state)

        adapter.mark_processed("signature_1")
        adapter.mark_processed("signature_2")
        adapter.mark_processed("signature_3")

        assert "signature_1" in buffer_state.processed_signatures
        assert "signature_2" in buffer_state.processed_signatures
        assert "signature_3" in buffer_state.processed_signatures
        assert len(buffer_state.processed_signatures) == 3

    def test_consume_cursor_bounds(self) -> None:
        """Test that cursor doesn't exceed buffer length."""
        buffer_state = ToolCallBufferState()
        call1 = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        buffer_state.detected_calls = [call1]
        buffer_state.reactor_cursor = 0

        adapter = StreamBufferAdapter(buffer_state)
        # Consume first time
        calls1 = adapter.consume_new_reactor_calls()
        assert len(calls1) == 1
        assert buffer_state.reactor_cursor == 1

        # Consume second time - should be empty
        calls2 = adapter.consume_new_reactor_calls()
        assert calls2 == []
        assert buffer_state.reactor_cursor == 1  # Cursor doesn't exceed length

    def test_consume_skips_invalid_tool_calls(self) -> None:
        """Test that invalid tool calls are skipped without crashing."""
        buffer_state = ToolCallBufferState()
        valid_call = {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test_tool", "arguments": '{"key": "value"}'},
        }
        invalid_call = {"invalid": "structure"}  # Missing required fields
        buffer_state.detected_calls = [valid_call, invalid_call]
        buffer_state.reactor_cursor = 0

        adapter = StreamBufferAdapter(buffer_state)
        calls = adapter.consume_new_reactor_calls()

        # Should return only the valid call
        assert len(calls) == 1
        assert calls[0].id == "call_1"
        # Cursor should still advance
        assert buffer_state.reactor_cursor == 2
