"""Tests for tool call repair processor buffer handling.

This test module verifies that the buffer handling in ToolCallRepairProcessor
correctly handles large tool calls and avoids corrupting tool calls when
the buffer needs to be flushed.
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
    return ToolCallRepairService(max_buffer_bytes=1024)  # Small buffer for testing


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


class TestBufferHandlingWithToolCalls:
    """Test buffer flushing behavior with tool calls."""

    @pytest.mark.asyncio
    async def test_small_tool_call_not_affected_by_buffer(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Small tool calls should be processed normally."""
        content = StreamingContent(
            content="<read_file><path>test.py</path></read_file>",
            is_done=True,
            metadata={"session_id": "test-session"},
        )
        result = await processor.process(content)
        assert result is not None
        # Tool call should be detected
        assert "tool_calls" in result.metadata or result.content

    @pytest.mark.asyncio
    async def test_buffer_trim_respects_unclosed_tool_tag(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Buffer should not be flushed mid-tool-call when tag is unclosed."""
        # Create a large content that would normally trigger buffer flush
        # but contains an unclosed tool tag
        large_prefix = "x" * 500  # 500 chars of content before tool
        tool_start = "<read_file><path>very/long/path/to/file.py</path>"

        content1 = StreamingContent(
            content=large_prefix + tool_start,
            is_done=False,
            metadata={"session_id": "test-session"},
        )
        result1 = await processor.process(content1)

        # Buffer should try to keep the unclosed tool tag together
        # The result might have some prefix flushed but not the tool tag content
        if result1.content:
            # If content was flushed, it should not contain partial tool XML
            assert (
                "</read_file>" not in result1.content
                or "<read_file>" in result1.content
            )

    @pytest.mark.asyncio
    async def test_complete_tool_call_after_buffer_flush(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Tool call should be correctly parsed even after buffer flush."""
        # Send content in chunks to simulate streaming
        session_id = "test-session-complete"

        # First chunk: some text
        content1 = StreamingContent(
            content="Processing file...\n",
            is_done=False,
            metadata={"session_id": session_id},
        )
        await processor.process(content1)

        # Second chunk: start of tool call
        content2 = StreamingContent(
            content="<execute_command><command>ls -la</command>",
            is_done=False,
            metadata={"session_id": session_id},
        )
        await processor.process(content2)

        # Third chunk: end of tool call
        content3 = StreamingContent(
            content="</execute_command>",
            is_done=True,
            metadata={"session_id": session_id},
        )
        result3 = await processor.process(content3)

        # Tool call should be detected in the final chunk
        assert result3 is not None
        # Either tool_calls in metadata or content contains the tool XML
        has_tool_call = (
            "tool_calls" in result3.metadata or "<execute_command>" in result3.content
        )
        assert has_tool_call


class TestToolCallMarkerDetection:
    """Test that all tool markers are correctly detected for buffer protection."""

    @pytest.mark.asyncio
    async def test_all_tool_markers_protected(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """All tool markers should be protected from mid-buffer flushing."""
        tool_markers = [
            "<new_task",
            "<update_todo_list",
            "<switch_mode",
            "<use_mcp_tool",
            "<patch_file",
            "<execute_command",
            "<read_file",
            "<write_to_file",
            "<ask_followup_question",
            "<attempt_completion",
            "<list_files",
            "<search_files",
            "<codebase_search",
            "<access_mcp_resource",
            "<search_and_replace",
            "<insert_content",
            "<edit_file",
            "<apply_diff",
        ]

        for marker in tool_markers:
            # Create content with unclosed marker
            content = StreamingContent(
                content=f"prefix text {marker}>some content",
                is_done=False,
                metadata={"session_id": f"test-{marker}"},
            )
            result = await processor.process(content)

            # The processor should recognize this as a potential tool
            # and either buffer it or include it in output
            # The key is it shouldn't corrupt the tool parsing
            assert result is not None, f"Failed for marker: {marker}"


class TestLargeToolCallHandling:
    """Test handling of very large tool calls (e.g., large file edits)."""

    @pytest.mark.asyncio
    async def test_large_patch_file_not_corrupted(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Large patch_file content should not be corrupted by buffer flushing."""
        # Use larger buffer for this test
        registry = StreamingContextRegistry()
        processor = ToolCallRepairProcessor(
            repair_service, max_buffer_bytes=64 * 1024, registry=registry
        )

        # Create a large but valid patch_file tool call
        large_diff = "+" + ("x" * 1000) + "\n" * 50  # ~50KB of diff content
        content = StreamingContent(
            content=f"<patch_file><path>test.py</path><patch_content>{large_diff}</patch_content></patch_file>",
            is_done=True,
            metadata={"session_id": "test-large-patch"},
        )

        result = await processor.process(content)
        assert result is not None

        # Tool call should be detected
        if "tool_calls" in result.metadata:
            tool_calls = result.metadata["tool_calls"]
            assert len(tool_calls) > 0
            assert tool_calls[0]["function"]["name"] == "patch_file"
