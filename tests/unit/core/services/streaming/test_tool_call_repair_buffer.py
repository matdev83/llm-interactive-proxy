"""Tests for tool call repair processor behavior.

DESIGN DECISION: Virtual tool call detection is disabled. Text/XML content must
pass through unchanged. Native OpenAI `tool_calls` are preserved, with one
exception: malformed streaming `function.arguments` may receive a minimal
suffix fix on terminal chunks.
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
    """Test transparent pass-through with native tool-call argument fixes."""

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

    @pytest.mark.asyncio
    async def test_repairs_missing_closing_brace_on_terminal_chunk(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """When streamed arguments are unterminated, append only the missing suffix."""
        first_chunk = StreamingContent(
            content="",
            is_done=False,
            metadata={
                "stream_id": "repair-stream-1",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "test.py"',
                        },
                    }
                ],
            },
        )
        terminal_chunk = StreamingContent(
            content="",
            is_done=True,
            metadata={
                "stream_id": "repair-stream-1",
                "finish_reason": "tool_calls",
            },
        )

        await processor.process(first_chunk)
        repaired = await processor.process(terminal_chunk)

        repaired_tool_calls = repaired.metadata.get("tool_calls")
        assert isinstance(repaired_tool_calls, list)
        assert len(repaired_tool_calls) == 1
        assert repaired_tool_calls[0]["index"] == 0
        assert repaired_tool_calls[0]["function"]["arguments"] == "}"

    @pytest.mark.asyncio
    async def test_repairs_suffix_on_existing_terminal_tool_call_fragment(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """If terminal chunk already has a fragment, suffix is appended in-place."""
        first_chunk = StreamingContent(
            content="",
            is_done=False,
            metadata={
                "stream_id": "repair-stream-2",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_456",
                        "type": "function",
                        "function": {
                            "name": "search_files",
                            "arguments": '{"path": "src"',
                        },
                    }
                ],
            },
        )
        terminal_chunk = StreamingContent(
            content="",
            is_done=True,
            metadata={
                "stream_id": "repair-stream-2",
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "index": 0,
                        "type": "function",
                        "function": {"arguments": ', "recursive": true'},
                    }
                ],
            },
        )

        await processor.process(first_chunk)
        repaired = await processor.process(terminal_chunk)

        repaired_tool_calls = repaired.metadata.get("tool_calls")
        assert isinstance(repaired_tool_calls, list)
        assert len(repaired_tool_calls) == 1
        assert repaired_tool_calls[0]["function"]["arguments"] == ', "recursive": true}'
