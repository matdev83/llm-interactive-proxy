"""
Regression tests for tool call handling in the streaming pipeline.

DESIGN DECISION: Virtual tool call detection (parsing XML from message content)
has been DISABLED. The proxy now passes content through transparently.

These tests verify:
1. Content passes through unchanged (no XML detection, no buffering)
2. Native tool_calls (already structured) are passed through unchanged

Clients like Cline, RooCode, KiloCode parse XML tool calls themselves.
The proxy should not interfere with this.
"""

from __future__ import annotations

import pytest
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
)
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService


class TestToolCallRepairProcessorPassThrough:
    """
    Tests that the ToolCallRepairProcessor passes content through unchanged.

    After disabling virtual tool call detection, the processor should:
    - Pass all content through without modification
    - Not buffer or detect XML
    - Not modify finish_reason
    - Preserve native tool_calls if present
    """

    @pytest.fixture
    def processor(self) -> ToolCallRepairProcessor:
        repair_service = ToolCallRepairService()
        registry = StreamingContextRegistry()
        return ToolCallRepairProcessor(
            tool_call_repair_service=repair_service, registry=registry
        )

    @pytest.mark.asyncio
    async def test_content_passes_through_unchanged(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Content should pass through without modification."""
        content = StreamingContent(
            content="Hello, world!",
            is_done=False,
            metadata={"session_id": "test-session"},
        )

        result = await processor.process(content)

        assert result.content == "Hello, world!"
        assert result.is_done is False

    @pytest.mark.asyncio
    async def test_xml_content_passes_through_unchanged(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """XML content should pass through without detection or modification."""
        xml_content = """<execute_command>
<command>git status</command>
</execute_command>"""

        content = StreamingContent(
            content=xml_content,
            is_done=True,
            metadata={"session_id": "test-session"},
        )

        result = await processor.process(content)

        # Content unchanged - no detection, no modification
        assert result.content == xml_content
        # No tool_calls added (XML detection disabled)
        assert result.metadata.get("tool_calls") is None
        # finish_reason not modified
        assert result.metadata.get("finish_reason") is None

    @pytest.mark.asyncio
    async def test_client_specific_tags_pass_through(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Client-specific tags like <brain_dump> should pass through unchanged."""
        content_with_brain_dump = """I'll check the tests.<brain_dump>
The user wants to verify all tests pass.
</brain_dump>"""

        content = StreamingContent(
            content=content_with_brain_dump,
            is_done=True,
            metadata={"session_id": "test-session"},
        )

        result = await processor.process(content)

        # Content unchanged - including client-specific tags
        assert "<brain_dump>" in result.content
        assert "I'll check the tests." in result.content

    @pytest.mark.asyncio
    async def test_native_tool_calls_preserved(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Native tool_calls (already structured) should be preserved."""
        native_tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "get_weather", "arguments": '{"city": "NYC"}'},
            }
        ]

        content = StreamingContent(
            content="",
            is_done=True,
            metadata={
                "session_id": "test-session",
                "tool_calls": native_tool_calls,
                "finish_reason": "tool_calls",
            },
        )

        result = await processor.process(content)

        # Native tool_calls passed through unchanged
        assert result.metadata.get("tool_calls") == native_tool_calls
        assert result.metadata.get("finish_reason") == "tool_calls"

    @pytest.mark.asyncio
    async def test_streaming_chunks_not_buffered(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Streaming chunks should pass through immediately, not be buffered."""
        chunk1 = StreamingContent(
            content="<execute",
            is_done=False,
            metadata={"session_id": "test-session"},
        )
        chunk2 = StreamingContent(
            content="_command>",
            is_done=False,
            metadata={"session_id": "test-session"},
        )

        result1 = await processor.process(chunk1)
        result2 = await processor.process(chunk2)

        # Both chunks pass through immediately (no buffering)
        assert result1.content == "<execute"
        assert result2.content == "_command>"
