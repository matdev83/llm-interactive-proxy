"""
Regression tests for tool call handling with various clients.

DESIGN DECISION: Virtual tool call detection (parsing XML from message content)
has been DISABLED. The proxy now passes content through transparently.

These tests verify:
1. Content passes through unchanged for Cline-style clients (KiloCode, RooCode)
2. Content passes through unchanged for Factory Droid
3. Native tool_calls (already structured) are passed through unchanged

Clients parse XML tool calls themselves. The proxy should not interfere.
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


class TestKiloCodeCompatibility:
    """Tests that KiloCode-style XML passes through unchanged."""

    @pytest.fixture
    def processor(self) -> ToolCallRepairProcessor:
        repair_service = ToolCallRepairService()
        registry = StreamingContextRegistry()
        return ToolCallRepairProcessor(
            tool_call_repair_service=repair_service, registry=registry
        )

    @pytest.mark.asyncio
    async def test_execute_command_passes_through(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """KiloCode execute_command XML passes through unchanged."""
        xml_content = """<execute_command>
<command>git status</command>
<requires_approval>false</requires_approval>
</execute_command>"""

        content = StreamingContent(
            content=xml_content,
            is_done=True,
            metadata={"session_id": "kilocode-session"},
        )

        result = await processor.process(content)

        # XML passed through unchanged
        assert "<execute_command>" in result.content
        assert "<command>git status</command>" in result.content

    @pytest.mark.asyncio
    async def test_read_file_passes_through(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """KiloCode read_file XML passes through unchanged."""
        xml_content = """<read_file>
<path>src/main.py</path>
</read_file>"""

        content = StreamingContent(
            content=xml_content,
            is_done=True,
            metadata={"session_id": "kilocode-session"},
        )

        result = await processor.process(content)

        assert "<read_file>" in result.content
        assert "<path>src/main.py</path>" in result.content


class TestFactoryDroidCompatibility:
    """Tests that Factory Droid content passes through unchanged."""

    @pytest.fixture
    def processor(self) -> ToolCallRepairProcessor:
        repair_service = ToolCallRepairService()
        registry = StreamingContextRegistry()
        return ToolCallRepairProcessor(
            tool_call_repair_service=repair_service, registry=registry
        )

    @pytest.mark.asyncio
    async def test_brain_dump_passes_through(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Factory Droid brain_dump tags pass through unchanged."""
        content_with_brain_dump = """I'll check the test suite.<brain_dump>
The user wants me to verify if all tests pass and fix any failures.
1. Run the full test suite
2. Check for any failures
</brain_dump>"""

        content = StreamingContent(
            content=content_with_brain_dump,
            is_done=True,
            metadata={"session_id": "droid-session"},
        )

        result = await processor.process(content)

        # brain_dump passed through unchanged
        assert "<brain_dump>" in result.content
        assert "I'll check the test suite." in result.content

    @pytest.mark.asyncio
    async def test_memory_bank_passes_through(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Factory Droid memory_bank tags pass through unchanged."""
        content_with_memory = """<memory_bank>
<knowledge_node id="1">
User prefers detailed explanations.
</knowledge_node>
</memory_bank>"""

        content = StreamingContent(
            content=content_with_memory,
            is_done=True,
            metadata={"session_id": "droid-session"},
        )

        result = await processor.process(content)

        # memory_bank passed through unchanged
        assert "<memory_bank>" in result.content
        assert "<knowledge_node" in result.content

    @pytest.mark.asyncio
    async def test_namespaced_tool_calls_pass_through(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Factory Droid namespaced tool calls pass through unchanged."""
        xml_content = """<ClientControls:run_terminal_command>
<command>npm test</command>
<wait_for_completion>true</wait_for_completion>
</ClientControls:run_terminal_command>"""

        content = StreamingContent(
            content=xml_content,
            is_done=True,
            metadata={"session_id": "droid-session"},
        )

        result = await processor.process(content)

        # Namespaced tool call passed through unchanged
        assert "<ClientControls:run_terminal_command>" in result.content
        assert "<command>npm test</command>" in result.content


class TestNativeToolCallsPreserved:
    """Tests that native tool_calls (structured) are preserved."""

    @pytest.fixture
    def processor(self) -> ToolCallRepairProcessor:
        repair_service = ToolCallRepairService()
        registry = StreamingContextRegistry()
        return ToolCallRepairProcessor(
            tool_call_repair_service=repair_service, registry=registry
        )

    @pytest.mark.asyncio
    async def test_native_tool_calls_preserved(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Native tool_calls in metadata are preserved unchanged."""
        native_tool_calls = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "arguments": '{"command": "ls -la"}',
                },
            }
        ]

        content = StreamingContent(
            content="",
            is_done=True,
            metadata={
                "session_id": "native-session",
                "tool_calls": native_tool_calls,
                "finish_reason": "tool_calls",
            },
        )

        result = await processor.process(content)

        # Native tool_calls preserved
        assert result.metadata.get("tool_calls") == native_tool_calls
        assert result.metadata.get("finish_reason") == "tool_calls"
