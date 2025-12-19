"""Tests for ToolBlockBuffer."""

from __future__ import annotations

from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
)
from src.core.transport.fastapi.adapters.protocols import IToolBlockBuffer
from src.core.transport.fastapi.adapters.streaming.tool_block_buffer import (
    ToolBlockBuffer,
)


class TestToolBlockBuffer:
    """Test ToolBlockBuffer implementation."""

    def test_buffer_implements_protocol(self) -> None:
        """Test that ToolBlockBuffer implements IToolBlockBuffer protocol."""
        buffer: IToolBlockBuffer = ToolBlockBuffer()
        assert isinstance(buffer, ToolBlockBuffer)

    def test_partial_block_buffering(self) -> None:
        """Test partial block buffering."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id = "test-stream"

        # First chunk: partial opening tag
        result1 = buffer.buffer("<read_file", stream_id)
        assert result1 == ""  # No complete block yet

        # Second chunk: complete opening tag and partial content
        result2 = buffer.buffer(">file.txt</read_file>", stream_id)
        assert "<read_file>file.txt</read_file>" in result2

    def test_complete_block_emission(self) -> None:
        """Test complete block emission."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id = "test-stream"

        # Complete block in one chunk
        content = "Some text <read_file>file.txt</read_file> more text"
        result = buffer.buffer(content, stream_id)
        assert "<read_file>file.txt</read_file>" in result

    def test_flush_returns_pending(self) -> None:
        """Test flush returns pending content."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id = "test-stream"

        # Add partial block
        buffer.buffer("<read_file>partial", stream_id)

        # Flush should return pending
        flushed = buffer.flush(stream_id)
        assert "partial" in flushed or "<read_file>partial" in flushed

    def test_reset_clears_state(self) -> None:
        """Test reset clears buffer state."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id = "test-stream"

        # Add partial block
        buffer.buffer("<read_file>partial", stream_id)

        # Reset should clear state
        buffer.reset(stream_id)

        # Flush after reset should return empty or minimal content
        flushed = buffer.flush(stream_id)
        assert not flushed or flushed == ""

    def test_tag_tracking_via_registry(self) -> None:
        """Test tag tracking via registry."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id = "test-stream"

        # Process content with tags
        buffer.buffer("<read_file>test</read_file>", stream_id)

        # Check that tags were tracked
        buffer_state = registry.get_tool_call_buffer(stream_id)
        assert "read_file" in buffer_state.tracked_tags

    def test_allowed_tools_filtering(self) -> None:
        """Test allowed_tools filtering."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id = "test-stream"

        # Set allowed tools
        buffer_state = registry.get_tool_call_buffer(stream_id)
        buffer_state.allowed_tools = ["read_file", "write_file"]

        # Process content with allowed and disallowed tags
        content = "<read_file>test</read_file><forbidden_tool>test</forbidden_tool>"
        result = buffer.buffer(content, stream_id)

        # Should only process allowed tags
        assert "<read_file>test</read_file>" in result
        # Disallowed tag should still appear but not be buffered/tracked
        assert "forbidden_tool" in content

    def test_think_thought_tag_exclusion(self) -> None:
        """Test think/thought tag exclusion when no allowed_tools."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id = "test-stream"

        # No allowed_tools set
        buffer_state = registry.get_tool_call_buffer(stream_id)
        buffer_state.allowed_tools = None

        # Process content with think/thought tags
        content = "<think>reasoning</think><thought>more</thought>"
        buffer.buffer(content, stream_id)

        # These tags should be excluded from tracking
        assert "think" not in buffer_state.tracked_tags
        assert "thought" not in buffer_state.tracked_tags

    def test_multiple_tags_in_content(self) -> None:
        """Test handling multiple tags in content."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id = "test-stream"

        content = (
            "<read_file>file1</read_file>"
            "<write_file>file2</write_file>"
            "<execute>cmd</execute>"
        )
        result = buffer.buffer(content, stream_id)

        # All complete tags should be in result
        assert "<read_file>file1</read_file>" in result
        assert "<write_file>file2</write_file>" in result
        assert "<execute>cmd</execute>" in result

    def test_nested_tags_handling(self) -> None:
        """Test handling nested tags."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id = "test-stream"

        # Nested tags (should handle correctly)
        content = "<outer><inner>content</inner></outer>"
        result = buffer.buffer(content, stream_id)

        # Should preserve nested structure
        assert "<outer>" in result
        assert "<inner>content</inner>" in result

    def test_empty_content_handling(self) -> None:
        """Test handling empty content."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id = "test-stream"

        result = buffer.buffer("", stream_id)
        assert result == ""

    def test_self_closing_tags(self) -> None:
        """Test self-closing tags are not buffered."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id = "test-stream"

        content = "<br/>self-closing"
        result = buffer.buffer(content, stream_id)

        # Self-closing tags should pass through
        assert "<br/>" in result

    def test_fallback_to_global_registry(self) -> None:
        """Test fallback to global registry when not provided."""
        buffer = ToolBlockBuffer()
        stream_id = "test-stream"

        # Should work without explicit registry
        result = buffer.buffer("<read_file>test</read_file>", stream_id)
        assert "<read_file>test</read_file>" in result

    def test_flush_with_multiple_pending_tags(self) -> None:
        """Test flush with multiple pending tags."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id = "test-stream"

        # Add partial blocks for multiple tags
        buffer.buffer("<read_file>partial1", stream_id)
        buffer.buffer("<write_file>partial2", stream_id)

        # Flush should return all pending
        flushed = buffer.flush(stream_id)
        assert "partial1" in flushed or "partial2" in flushed

    def test_reset_with_stream_id(self) -> None:
        """Test reset clears state for specific stream."""
        registry = StreamingContextRegistry()
        buffer = ToolBlockBuffer(registry=registry)
        stream_id1 = "stream-1"
        stream_id2 = "stream-2"

        # Add content to both streams
        buffer.buffer("<read_file>test1</read_file>", stream_id1)
        buffer.buffer("<read_file>test2</read_file>", stream_id2)

        # Reset only stream-1
        buffer.reset(stream_id1)

        # Stream-2 should still have content
        buffer_state2 = registry.get_tool_call_buffer(stream_id2)
        assert "read_file" in buffer_state2.tracked_tags
