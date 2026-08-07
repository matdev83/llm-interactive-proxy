"""Tests for ToolCallDeduplicator.

Following TDD methodology: tests written before implementation.
"""

from __future__ import annotations

import pytest
from src.core.domain.chat import FunctionCall, ToolCall
from src.core.interfaces.tool_call_deduplicator_interface import (
    IToolCallDeduplicator,
)
from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
)
from src.core.services.tool_call_reactor.deduplicator import (
    ToolCallDeduplicator,
)
from src.core.services.tool_call_reactor.stream_buffer_adapter import (
    StreamBufferAdapter,
)
from src.tool_call_loop.lifecycle_registry import (
    ToolCallLifecycleRegistry,
    build_reactor_processing_signature,
)


class TestFilterNewCalls:
    """Tests for filtering new tool calls."""

    @pytest.mark.asyncio
    async def test_filter_new_calls_with_buffered_calls(self) -> None:
        """Test that buffered calls are consumed from buffer state."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        registry = StreamingContextRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"
        buffer_state_obj = registry.get_tool_call_buffer(stream_key)
        buffer_state = StreamBufferAdapter(buffer_state_obj)

        # Add calls to buffer
        call1 = ToolCall(
            id="call_1",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )
        call2 = ToolCall(
            id="call_2",
            function=FunctionCall(name="test_tool2", arguments='{"key2": "value2"}'),
        )
        buffer_state_obj.detected_calls = [
            call1.model_dump(),
            call2.model_dump(),
        ]
        buffer_state_obj.reactor_cursor = 0

        # Filter calls (should consume from buffer)
        result = await resolver.filter_new_calls(
            [], stream_key, buffer_state, is_streaming=True
        )

        # Should return buffered calls
        assert len(result) == 2
        assert result[0].id == "call_1"
        assert result[1].id == "call_2"
        # Cursor should be advanced
        assert buffer_state_obj.reactor_cursor == 2

    @pytest.mark.asyncio
    async def test_filter_new_calls_with_non_buffered_calls(self) -> None:
        """Test that non-buffered calls are checked against lifecycle registry."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"
        call1 = ToolCall(
            id="call_1",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )
        call2 = ToolCall(
            id="call_2",
            function=FunctionCall(name="test_tool2", arguments='{"key2": "value2"}'),
        )

        # Filter calls (non-buffered)
        result = await resolver.filter_new_calls(
            [call1, call2], stream_key, None, is_streaming=False
        )

        # Should return both calls (new)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_filter_new_calls_skips_already_processed(self) -> None:
        """Test that already-processed calls are skipped."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        registry = StreamingContextRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"
        buffer_state_obj = registry.get_tool_call_buffer(stream_key)
        buffer_state = StreamBufferAdapter(buffer_state_obj)

        call1 = ToolCall(
            id="call_1",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )

        # Mark as processed
        from src.tool_call_loop.lifecycle_registry import build_tool_call_signature

        signature = build_tool_call_signature(call1.model_dump())
        buffer_state.mark_processed(signature)

        # Filter calls
        result = await resolver.filter_new_calls(
            [call1], stream_key, buffer_state, is_streaming=False
        )

        # Should skip already-processed call
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_filter_new_calls_uses_interface_method(self) -> None:
        """Test that deduplicator uses is_processed() interface method."""
        from unittest.mock import MagicMock

        lifecycle_registry = ToolCallLifecycleRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"
        call1 = ToolCall(
            id="call_1",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )

        # Create mock buffer state
        mock_buffer_state = MagicMock()
        mock_buffer_state.is_processed.return_value = True
        mock_buffer_state.consume_new_reactor_calls.return_value = []

        # Filter calls
        result = await resolver.filter_new_calls(
            [call1], stream_key, mock_buffer_state, is_streaming=False
        )

        # Should skip call because is_processed returns True
        assert len(result) == 0
        # Verify interface method was called
        mock_buffer_state.is_processed.assert_called_once()

    @pytest.mark.asyncio
    async def test_filter_new_calls_skips_duplicate_detections(self) -> None:
        """Test that duplicate detections are skipped via lifecycle registry."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"
        call1 = ToolCall(
            id="call_1",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )

        # First detection should succeed
        result1 = await resolver.filter_new_calls(
            [call1], stream_key, None, is_streaming=False
        )
        assert len(result1) == 1

        # Second detection should be skipped
        result2 = await resolver.filter_new_calls(
            [call1], stream_key, None, is_streaming=False
        )
        assert len(result2) == 0

    @pytest.mark.asyncio
    async def test_filter_new_calls_streaming_stable_across_late_tool_call_id(
        self,
    ) -> None:
        """Streaming deltas share index+name before id; reactor must dedupe once."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)
        stream_key = "test-stream-late-id"

        early = ToolCall.model_validate(
            {
                "type": "function",
                "index": 0,
                "function": {"name": "bash", "arguments": "{"},
            }
        )
        late = ToolCall.model_validate(
            {
                "type": "function",
                "index": 0,
                "id": "call_abc123",
                "function": {"name": "bash", "arguments": '{"cmd":"ls"}'},
            }
        )

        first = await resolver.filter_new_calls(
            [early], stream_key, None, is_streaming=True
        )
        assert len(first) == 1
        assert (
            build_reactor_processing_signature(early.model_dump(), is_streaming=True)
            == "idx:0:bash"
        )

        await resolver.mark_processed(
            stream_key,
            build_reactor_processing_signature(early.model_dump(), is_streaming=True),
            None,
        )

        second = await resolver.filter_new_calls(
            [late], stream_key, None, is_streaming=True
        )
        assert len(second) == 0

    @pytest.mark.asyncio
    async def test_filter_new_calls_handles_none_buffer_state(self) -> None:
        """Test that None buffer state is handled gracefully (degraded mode)."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"
        call1 = ToolCall(
            id="call_1",
            function=FunctionCall(name="test_tool", arguments='{"key": "value"}'),
        )

        # Filter with None buffer state
        result = await resolver.filter_new_calls(
            [call1], stream_key, None, is_streaming=False
        )

        # Should still process non-buffered calls
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_filter_new_calls_empty_list(self) -> None:
        """Test that empty list returns empty list."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"

        result = await resolver.filter_new_calls(
            [], stream_key, None, is_streaming=False
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_filter_new_calls_mixed_buffered_and_non_buffered(self) -> None:
        """Test filtering when both buffered and non-buffered calls exist."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        registry = StreamingContextRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"
        buffer_state_obj = registry.get_tool_call_buffer(stream_key)
        buffer_state = StreamBufferAdapter(buffer_state_obj)

        # Add buffered call
        buffered_call = ToolCall(
            id="buffered_1",
            function=FunctionCall(name="buffered_tool", arguments='{"key": "value"}'),
        )
        buffer_state_obj.detected_calls = [buffered_call.model_dump()]
        buffer_state_obj.reactor_cursor = 0

        # Non-buffered call
        non_buffered_call = ToolCall(
            id="non_buffered_1",
            function=FunctionCall(
                name="non_buffered_tool", arguments='{"key2": "value2"}'
            ),
        )

        # Filter calls (buffered + non-buffered)
        # Note: In real usage, buffered calls come from buffer_state.consume_new_reactor_calls()
        # and non-buffered come from the response. For this test, we'll simulate by
        # calling filter with non-buffered calls while buffer has calls.
        buffered_result = await resolver.filter_new_calls(
            [], stream_key, buffer_state, is_streaming=True
        )
        non_buffered_result = await resolver.filter_new_calls(
            [non_buffered_call], stream_key, buffer_state, is_streaming=True
        )

        # Both should be processed
        assert len(buffered_result) == 1
        assert len(non_buffered_result) == 1


class TestMarkProcessed:
    """Tests for marking tool calls as processed."""

    @pytest.mark.asyncio
    async def test_mark_processed_updates_lifecycle_registry(self) -> None:
        """Test that marking processed updates lifecycle registry."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"
        signature = "test_tool:abc123"

        # Mark as processed
        await resolver.mark_processed(stream_key, signature, None)

        # Verify it's marked as processed
        assert await resolver.is_processed(stream_key, signature)

    @pytest.mark.asyncio
    async def test_mark_processed_updates_buffer_state(self) -> None:
        """Test that marking processed updates buffer state."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        registry = StreamingContextRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"
        buffer_state_obj = registry.get_tool_call_buffer(stream_key)
        buffer_state = StreamBufferAdapter(buffer_state_obj)
        signature = "test_tool:abc123"

        # Mark as processed
        await resolver.mark_processed(stream_key, signature, buffer_state)

        # Verify it's in buffer processed signatures
        assert signature in buffer_state_obj.processed_signatures

    @pytest.mark.asyncio
    async def test_mark_processed_handles_none_buffer_state(self) -> None:
        """Test that None buffer state is handled gracefully."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"
        signature = "test_tool:abc123"

        # Should not crash with None buffer state
        await resolver.mark_processed(stream_key, signature, None)

        # Should still update lifecycle registry
        assert await resolver.is_processed(stream_key, signature)


class TestIsProcessed:
    """Tests for checking if tool calls are processed."""

    @pytest.mark.asyncio
    async def test_is_processed_returns_false_for_new_signature(self) -> None:
        """Test that new signatures return False."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"
        signature = "test_tool:abc123"

        assert not await resolver.is_processed(stream_key, signature)

    @pytest.mark.asyncio
    async def test_is_processed_returns_true_after_marking(self) -> None:
        """Test that signatures return True after marking."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        stream_key = "test-stream"
        signature = "test_tool:abc123"

        await resolver.mark_processed(stream_key, signature, None)
        assert await resolver.is_processed(stream_key, signature)

    @pytest.mark.asyncio
    async def test_is_processed_handles_different_streams(self) -> None:
        """Test that different streams are isolated."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        signature = "test_tool:abc123"

        # Mark in stream 1
        await resolver.mark_processed("stream_1", signature, None)
        assert await resolver.is_processed("stream_1", signature)

        # Should not be processed in stream 2
        assert not await resolver.is_processed("stream_2", signature)


class TestDeduplicatorInterface:
    """Tests for interface compliance."""

    def test_deduplicator_implements_interface(self) -> None:
        """Test that deduplicator implements IToolCallDeduplicator."""
        lifecycle_registry = ToolCallLifecycleRegistry()
        resolver = ToolCallDeduplicator(lifecycle_registry)

        assert isinstance(resolver, IToolCallDeduplicator)
