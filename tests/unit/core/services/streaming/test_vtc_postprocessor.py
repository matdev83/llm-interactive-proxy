"""Unit tests for VTC Post-Processor."""

import json

import pytest
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.services.streaming.vtc_postprocessor import (
    VTCPostProcessor,
    VTCPostProcessorConfig,
)


class TestVTCPostProcessorPassThrough:
    """Tests for VTC post-processor pass-through behavior."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(self, registry: StreamingContextRegistry) -> VTCPostProcessor:
        """Create a processor instance."""
        return VTCPostProcessor(registry=registry)

    @pytest.mark.asyncio
    async def test_pass_through_when_vtc_disabled(
        self, processor: VTCPostProcessor
    ) -> None:
        """Test that content passes through unchanged when vtc_enabled=False."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "arguments": json.dumps({"arg": "value"}),
                },
            }
        ]

        content = StreamingContent(
            content="Some text",
            metadata={"vtc_enabled": False, "tool_calls": tool_calls},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Content should be unchanged
        assert result.content == "Some text"
        # tool_calls should still be in metadata (not converted to XML)
        assert "tool_calls" in result.metadata

    @pytest.mark.asyncio
    async def test_pass_through_when_vtc_not_in_metadata(
        self, processor: VTCPostProcessor
    ) -> None:
        """Test that content passes through when vtc_enabled is not in metadata."""
        content = StreamingContent(
            content="Some text",
            metadata={},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        assert result.content == "Some text"

    @pytest.mark.asyncio
    async def test_pass_through_when_no_tool_calls(
        self, processor: VTCPostProcessor
    ) -> None:
        """Test that content passes through when no tool_calls in metadata."""
        content = StreamingContent(
            content="Some text",
            metadata={"vtc_enabled": True},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        assert result.content == "Some text"


class TestVTCPostProcessorSerialization:
    """Tests for VTC post-processor tool call serialization."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(self, registry: StreamingContextRegistry) -> VTCPostProcessor:
        """Create a processor instance."""
        return VTCPostProcessor(registry=registry)

    @pytest.mark.asyncio
    async def test_serializes_tool_call_to_xml(
        self, processor: VTCPostProcessor
    ) -> None:
        """Test that tool calls are serialized to XML format."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "arguments": json.dumps({"command": "ls -la"}),
                },
            }
        ]

        content = StreamingContent(
            content="",
            metadata={"vtc_enabled": True, "tool_calls": tool_calls},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Should have XML content
        assert "<function_calls>" in result.content
        assert '<invoke name="execute_command">' in result.content
        assert '<parameter name="command">ls -la</parameter>' in result.content
        assert "</function_calls>" in result.content

        # tool_calls should be removed from metadata
        assert "tool_calls" not in result.metadata

    @pytest.mark.asyncio
    async def test_serializes_multiple_tool_calls(
        self, processor: VTCPostProcessor
    ) -> None:
        """Test serialization of multiple tool calls."""
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "tool_a",
                    "arguments": json.dumps({"arg": "a"}),
                },
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {
                    "name": "tool_b",
                    "arguments": json.dumps({"arg": "b"}),
                },
            },
        ]

        content = StreamingContent(
            content="",
            metadata={"vtc_enabled": True, "tool_calls": tool_calls},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Should have both tool calls
        assert result.content.count("<invoke") == 2
        assert '<invoke name="tool_a">' in result.content
        assert '<invoke name="tool_b">' in result.content

    @pytest.mark.asyncio
    async def test_appends_xml_to_existing_content(
        self, processor: VTCPostProcessor
    ) -> None:
        """Test that XML is appended to existing content."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "arguments": "{}",
                },
            }
        ]

        content = StreamingContent(
            content="Some existing text",
            metadata={"vtc_enabled": True, "tool_calls": tool_calls},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Should have both original text and XML
        assert result.content.startswith("Some existing text")
        assert "<function_calls>" in result.content
        assert result.content.index("Some existing text") < result.content.index(
            "<function_calls>"
        )

    @pytest.mark.asyncio
    async def test_removes_tool_calls_from_metadata(
        self, processor: VTCPostProcessor
    ) -> None:
        """Test that tool_calls is removed from metadata after serialization."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "arguments": "{}",
                },
            }
        ]

        content = StreamingContent(
            content="",
            metadata={
                "vtc_enabled": True,
                "tool_calls": tool_calls,
                "other_field": "preserved",
            },
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # tool_calls should be removed
        assert "tool_calls" not in result.metadata
        # Other fields should be preserved
        assert result.metadata.get("other_field") == "preserved"
        assert result.metadata.get("vtc_enabled") is True


class TestVTCPostProcessorConfig:
    """Tests for VTC post-processor configuration."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.mark.asyncio
    async def test_config_newline_count(
        self, registry: StreamingContextRegistry
    ) -> None:
        """Test that newline count configuration is respected."""
        config = VTCPostProcessorConfig(prepend_newlines=True, newline_count=3)
        processor = VTCPostProcessor(registry=registry, config=config)

        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "arguments": "{}",
                },
            }
        ]

        content = StreamingContent(
            content="Text",
            metadata={"vtc_enabled": True, "tool_calls": tool_calls},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Should have 3 newlines between text and XML
        assert "Text\n\n\n<function_calls>" in result.content

    @pytest.mark.asyncio
    async def test_config_no_newlines(self, registry: StreamingContextRegistry) -> None:
        """Test configuration with no newlines before XML."""
        config = VTCPostProcessorConfig(prepend_newlines=False)
        processor = VTCPostProcessor(registry=registry, config=config)

        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "arguments": "{}",
                },
            }
        ]

        content = StreamingContent(
            content="Text",
            metadata={"vtc_enabled": True, "tool_calls": tool_calls},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Should have no newlines between text and XML
        assert "Text<function_calls>" in result.content


class TestVTCPostProcessorReset:
    """Tests for VTC post-processor reset behavior."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(self, registry: StreamingContextRegistry) -> VTCPostProcessor:
        """Create a processor instance."""
        return VTCPostProcessor(registry=registry)

    def test_reset_does_not_raise(self, processor: VTCPostProcessor) -> None:
        """Test that reset() can be called without error."""
        # Should not raise
        processor.reset()


class TestVTCPostProcessorEdgeCases:
    """Tests for VTC post-processor edge cases."""

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        """Create a fresh registry for each test."""
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(self, registry: StreamingContextRegistry) -> VTCPostProcessor:
        """Create a processor instance."""
        return VTCPostProcessor(registry=registry)

    @pytest.mark.asyncio
    async def test_handles_empty_tool_calls_list(
        self, processor: VTCPostProcessor
    ) -> None:
        """Test handling of empty tool_calls list."""
        content = StreamingContent(
            content="Some text",
            metadata={"vtc_enabled": True, "tool_calls": []},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Should pass through unchanged
        assert result.content == "Some text"

    @pytest.mark.asyncio
    async def test_handles_bytes_content(self, processor: VTCPostProcessor) -> None:
        """Test handling of bytes content."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "arguments": "{}",
                },
            }
        ]

        content = StreamingContent(
            content=b"Some bytes",
            metadata={"vtc_enabled": True, "tool_calls": tool_calls},
            stream_id="test-stream",
        )

        result = await processor.process(content)

        # Should convert bytes to string and append XML
        assert "Some bytes" in result.content
        assert "<function_calls>" in result.content

    @pytest.mark.asyncio
    async def test_preserves_usage_on_output(self, processor: VTCPostProcessor) -> None:
        """Test that usage information is preserved."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "arguments": "{}",
                },
            }
        ]
        usage = {"prompt_tokens": 10, "completion_tokens": 20}

        content = StreamingContent(
            content="Text",
            metadata={"vtc_enabled": True, "tool_calls": tool_calls},
            stream_id="test-stream",
            usage=usage,
        )

        result = await processor.process(content)

        assert result.usage == usage

    @pytest.mark.asyncio
    async def test_preserves_stream_id(self, processor: VTCPostProcessor) -> None:
        """Test that stream_id is preserved."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "arguments": "{}",
                },
            }
        ]

        content = StreamingContent(
            content="Text",
            metadata={"vtc_enabled": True, "tool_calls": tool_calls},
            stream_id="my-stream-id",
        )

        result = await processor.process(content)

        assert result.stream_id == "my-stream-id"

    @pytest.mark.asyncio
    async def test_preserves_is_done_flag(self, processor: VTCPostProcessor) -> None:
        """Test that is_done flag is preserved."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "arguments": "{}",
                },
            }
        ]

        content = StreamingContent(
            content="Text",
            metadata={"vtc_enabled": True, "tool_calls": tool_calls},
            stream_id="test-stream",
            is_done=True,
        )

        result = await processor.process(content)

        assert result.is_done is True
