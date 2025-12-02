"""Tests for tool call repair processor pass-through behavior.

DESIGN DECISION: Virtual tool call detection has been DISABLED.
The processor now passes content through unchanged (no buffering).

These tests verify the pass-through behavior.
"""

import pytest
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService


@pytest.fixture
def repair_service() -> ToolCallRepairService:
    return ToolCallRepairService(max_buffer_bytes=1024)


@pytest.fixture
def registry() -> StreamingContextRegistry:
    return StreamingContextRegistry()


@pytest.fixture
def processor(
    repair_service: ToolCallRepairService, registry: StreamingContextRegistry
) -> ToolCallRepairProcessor:
    return ToolCallRepairProcessor(
        repair_service, max_buffer_bytes=1024, registry=registry
    )


class TestPassThroughBehavior:
    """Test that processor passes content through unchanged."""

    @pytest.mark.asyncio
    async def test_content_passes_through_unchanged(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Content should pass through without modification."""
        content = StreamingContent(
            content="<read_file><path>test.py</path></read_file>",
            is_done=True,
            metadata={"session_id": "test-session"},
        )
        result = await processor.process(content)

        # Content unchanged
        assert result.content == content.content
        # No tool_calls added (detection disabled)
        assert result.metadata.get("tool_calls") is None

    @pytest.mark.asyncio
    async def test_streaming_chunks_pass_through_immediately(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Streaming chunks should pass through immediately (no buffering)."""
        chunk1 = StreamingContent(
            content="<read_file>",
            is_done=False,
            metadata={"session_id": "test-session"},
        )
        chunk2 = StreamingContent(
            content="<path>test.py</path>",
            is_done=False,
            metadata={"session_id": "test-session"},
        )
        chunk3 = StreamingContent(
            content="</read_file>",
            is_done=True,
            metadata={"session_id": "test-session"},
        )

        result1 = await processor.process(chunk1)
        result2 = await processor.process(chunk2)
        result3 = await processor.process(chunk3)

        # All chunks pass through immediately
        assert result1.content == "<read_file>"
        assert result2.content == "<path>test.py</path>"
        assert result3.content == "</read_file>"

    @pytest.mark.asyncio
    async def test_native_tool_calls_preserved(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Native tool_calls in metadata are preserved."""
        native_call = {
            "id": "call_123",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"path": "test.py"}'},
        }
        content = StreamingContent(
            content="",
            is_done=True,
            metadata={
                "session_id": "test-session",
                "tool_calls": [native_call],
                "finish_reason": "tool_calls",
            },
        )

        result = await processor.process(content)

        # Native tool_calls preserved
        assert result.metadata.get("tool_calls") == [native_call]
        assert result.metadata.get("finish_reason") == "tool_calls"
