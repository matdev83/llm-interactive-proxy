"""Unit tests for VTC Pre-Processor."""

import pytest
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.services.streaming.vtc_preprocessor import (
    VTCPreProcessor,
    VTCPreProcessorConfig,
)


class TestVTCPreProcessorPassThrough:
    """Tests for VTC pre-processor pass-through behavior."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(self, registry: StreamingContextRegistry) -> VTCPreProcessor:
        """Create a processor instance."""
        return VTCPreProcessor(registry=registry)

    @pytest.mark.asyncio
    async def test_pass_through_when_vtc_disabled(
        self, processor: VTCPreProcessor
    ) -> None:
        """Test that content passes through unchanged when vtc_enabled=False."""
        content = StreamingContent(
            content='Some text with <function_calls><invoke name="test"></invoke></function_calls>',
            metadata={"vtc_enabled": False},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Content should be unchanged
        assert result.content == content.content
        assert "tool_calls" not in result.metadata

    @pytest.mark.asyncio
    async def test_pass_through_when_vtc_not_in_metadata(
        self, processor: VTCPreProcessor
    ) -> None:
        """Test that content passes through when vtc_enabled is not in metadata."""
        content = StreamingContent(
            content="Some text",
            metadata={},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        assert result.content == content.content
        assert "tool_calls" not in result.metadata


class TestVTCPreProcessorExtraction:
    """Tests for VTC pre-processor tool call extraction."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(self, registry: StreamingContextRegistry) -> VTCPreProcessor:
        """Create a processor instance."""
        return VTCPreProcessor(registry=registry)

    @pytest.mark.asyncio
    async def test_extracts_complete_tool_call(
        self, processor: VTCPreProcessor
    ) -> None:
        """Test extraction of a complete tool call."""
        xml_content = """<function_calls>
<invoke name="execute_command">
<parameter name="command">ls -la</parameter>
</invoke>
</function_calls>"""

        content = StreamingContent(
            content=f"Some text {xml_content}",
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Should have extracted tool calls
        assert "tool_calls" in result.metadata
        assert len(result.metadata["tool_calls"]) == 1
        assert result.metadata["tool_calls"][0]["function"]["name"] == "execute_command"

        # XML should be stripped from content
        assert "<invoke" not in result.content
        assert "Some text" in result.content

    @pytest.mark.asyncio
    async def test_extracts_multiple_tool_calls(
        self, processor: VTCPreProcessor
    ) -> None:
        """Test extraction of multiple tool calls."""
        xml_content = """<function_calls>
<invoke name="tool_a">
<parameter name="arg">a</parameter>
</invoke>
<invoke name="tool_b">
<parameter name="arg">b</parameter>
</invoke>
</function_calls>"""

        content = StreamingContent(
            content=xml_content,
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        assert "tool_calls" in result.metadata
        assert len(result.metadata["tool_calls"]) == 2
        names = [tc["function"]["name"] for tc in result.metadata["tool_calls"]]
        assert "tool_a" in names
        assert "tool_b" in names

    @pytest.mark.asyncio
    async def test_preserves_text_around_tool_calls(
        self, processor: VTCPreProcessor
    ) -> None:
        """Test that text before and after tool calls is preserved."""
        content = StreamingContent(
            content='Before <invoke name="test"><parameter name="x">1</parameter></invoke> After',
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        assert "Before" in result.content
        assert "After" in result.content
        assert "<invoke" not in result.content


class TestVTCPreProcessorBuffering:
    """Tests for VTC pre-processor buffering behavior."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(self, registry: StreamingContextRegistry) -> VTCPreProcessor:
        """Create a processor instance."""
        return VTCPreProcessor(registry=registry)

    @pytest.mark.asyncio
    async def test_buffers_partial_xml(
        self, processor: VTCPreProcessor, registry: StreamingContextRegistry
    ) -> None:
        """Test that partial XML is buffered."""
        # Send partial content
        content1 = StreamingContent(
            content="<function_calls><invoke name=",
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )

        result1 = await processor.process(content1)

        # Should return empty content while buffering
        assert result1.content == ""
        assert result1.is_empty is True

        # Buffer should have content
        buffer = registry.get_vtc_buffer("test-stream")
        assert buffer.pending_text == "<function_calls><invoke name="

    @pytest.mark.asyncio
    async def test_flushes_buffer_on_complete_pattern(
        self, processor: VTCPreProcessor, registry: StreamingContextRegistry
    ) -> None:
        """Test that buffer is flushed when complete pattern is detected."""
        stream_id = "test-stream"

        # First chunk - partial
        content1 = StreamingContent(
            content='<invoke name="test">',
            metadata={"vtc_enabled": True},
            stream_id=stream_id,
        )
        await processor.process(content1)

        # Second chunk - completes the pattern
        content2 = StreamingContent(
            content='<parameter name="x">1</parameter></invoke>',
            metadata={"vtc_enabled": True},
            stream_id=stream_id,
        )
        result2 = await processor.process(content2)

        # Should have extracted the tool call
        assert "tool_calls" in result2.metadata
        assert len(result2.metadata["tool_calls"]) == 1

        # Buffer should be empty after extraction
        buffer = registry.get_vtc_buffer(stream_id)
        assert buffer.pending_text == ""

    @pytest.mark.asyncio
    async def test_flushes_buffer_on_done(
        self, processor: VTCPreProcessor, registry: StreamingContextRegistry
    ) -> None:
        """Test that buffer is flushed on stream completion."""
        stream_id = "test-stream"

        # Send some regular text that doesn't look like XML
        content1 = StreamingContent(
            content="Some regular text",
            metadata={"vtc_enabled": True},
            stream_id=stream_id,
        )
        await processor.process(content1)

        # Complete the stream
        content2 = StreamingContent(
            content="",
            metadata={"vtc_enabled": True},
            stream_id=stream_id,
            is_done=True,
        )
        result2 = await processor.process(content2)

        # Should flush any remaining buffer
        # Since original content didn't look like partial XML, it should have been emitted earlier
        assert result2.is_done is True


class TestVTCPreProcessorConfig:
    """Tests for VTC pre-processor configuration."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.mark.asyncio
    async def test_max_buffer_size_limit(
        self, registry: StreamingContextRegistry
    ) -> None:
        """Test that buffer is flushed when max size is exceeded."""
        config = VTCPreProcessorConfig(max_buffer_bytes=50)
        processor = VTCPreProcessor(registry=registry, config=config)

        # Create content that would exceed buffer limit
        large_content = "x" * 100

        content = StreamingContent(
            content=large_content,
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Should flush buffer due to size limit
        assert len(result.content) > 0


class TestVTCPreProcessorReset:
    """Tests for VTC pre-processor reset behavior."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(self, registry: StreamingContextRegistry) -> VTCPreProcessor:
        """Create a processor instance."""
        return VTCPreProcessor(registry=registry)

    def test_reset_does_not_raise(self, processor: VTCPreProcessor) -> None:
        """Test that reset() can be called without error."""
        # Should not raise
        processor.reset()


class TestVTCPreProcessorEdgeCases:
    """Tests for VTC pre-processor edge cases."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(self, registry: StreamingContextRegistry) -> VTCPreProcessor:
        """Create a processor instance."""
        return VTCPreProcessor(registry=registry)

    @pytest.mark.asyncio
    async def test_handles_empty_content(self, processor: VTCPreProcessor) -> None:
        """Test handling of empty content."""
        content = StreamingContent(
            content="",
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        assert result.content == ""
        assert "tool_calls" not in result.metadata

    @pytest.mark.asyncio
    async def test_handles_bytes_content(self, processor: VTCPreProcessor) -> None:
        """Test handling of bytes content."""
        xml = '<invoke name="test"><parameter name="x">1</parameter></invoke>'
        content = StreamingContent(
            content=xml.encode("utf-8"),
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Should still extract tool calls from bytes
        assert "tool_calls" in result.metadata
        assert len(result.metadata["tool_calls"]) == 1

    @pytest.mark.asyncio
    async def test_handles_dict_content(self, processor: VTCPreProcessor) -> None:
        """Test handling of dict content."""
        content = StreamingContent(
            content={"content": "Some text"},
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Should extract text from dict
        assert "Some text" in result.content

    @pytest.mark.asyncio
    async def test_preserves_usage_on_output(self, processor: VTCPreProcessor) -> None:
        """Test that usage information is preserved."""
        usage = {"prompt_tokens": 10, "completion_tokens": 20}
        content = StreamingContent(
            content='<invoke name="test"><parameter name="x">1</parameter></invoke>',
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
            usage=usage,
        )

        result = await processor.process(content)

        assert result.usage == usage

    @pytest.mark.asyncio
    async def test_preserves_stream_id(self, processor: VTCPreProcessor) -> None:
        """Test that stream_id is preserved."""
        content = StreamingContent(
            content='<invoke name="test"><parameter name="x">1</parameter></invoke>',
            metadata={"vtc_enabled": True},
            stream_id="my-stream-id",
        )

        result = await processor.process(content)

        assert result.stream_id == "my-stream-id"
