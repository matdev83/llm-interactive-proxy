"""
Tests for ToolCallRepairService.

The ToolCallRepairService detects tool calls in various formats:
- JSON patterns
- XML patterns
- Text patterns

NOTE: The ToolCallRepairProcessor (streaming processor) has been simplified
to a transparent pass-through. Virtual tool call detection is now disabled.
Clients parse XML tool calls themselves.
"""

import json

import pytest
from src.core.services.tool_call_repair_service import ToolCallRepairService


@pytest.fixture
def repair_service() -> ToolCallRepairService:
    return ToolCallRepairService()


class TestToolCallRepairService:
    """Tests for the ToolCallRepairService detection logic."""

    def test_repair_tool_calls_json_pattern(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = (
            '{"function_call": {"name": "test_func", "arguments": {"arg1": "val1"}}}'
        )
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired.tool_call["function"]["name"] == "test_func"
        assert json.loads(repaired.tool_call["function"]["arguments"]) == {
            "arg1": "val1"
        }

    def test_json_decode_failure_falls_back_to_xml(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """If JSON decoding fails, the detector should still pick up XML tools."""
        content = '<write_to_file><path>f</path><content>{"foo": "bar"}</content></write_to_file>'
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired.tool_call["function"]["name"] == "write_to_file"

    def test_repair_tool_calls_text_pattern(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = 'TOOL CALL: test_func {"arg1": "val1"}'
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired.tool_call["function"]["name"] == "test_func"
        assert json.loads(repaired.tool_call["function"]["arguments"]) == {
            "arg1": "val1"
        }

    def test_repair_tool_calls_code_block_pattern(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = '```json\n{"tool": {"name": "test_func", "arguments": {"arg1": "val1"}}}\n```'
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired.tool_call["function"]["name"] == "test_func"
        assert json.loads(repaired.tool_call["function"]["arguments"]) == {
            "arg1": "val1"
        }

    def test_repair_tool_calls_xml_direct_tool(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = """
        <patch_file>
            <path>src/example.py</path>
            <patch_content>print("hello world")</patch_content>
        </patch_file>
        """
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired.tool_call["function"]["name"] == "patch_file"
        arguments = json.loads(repaired.tool_call["function"]["arguments"])
        assert arguments["path"] == "src/example.py"
        assert arguments["patch_content"] == 'print("hello world")'

    def test_repair_tool_calls_skipped_when_tools_disallowed(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = "<test_tool><arg1>val1</arg1></test_tool>"
        repaired = repair_service.repair_tool_calls(content, allowed_tools=[])
        assert repaired is None

    def test_repair_tool_calls_whitelist_mode(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """When allowed_tools is provided, only those tools are detected."""
        content = """<brain_dump>
Some internal thinking content.
</brain_dump>"""
        # brain_dump not in whitelist - should not be detected
        repaired = repair_service.repair_tool_calls(
            content, allowed_tools=["execute_command"]
        )
        assert repaired is None

    def test_repair_tool_calls_whitelist_allows_matching_tool(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Whitelisted tools are detected."""
        content = """<execute_command>
<command>git status</command>
</execute_command>"""
        repaired = repair_service.repair_tool_calls(
            content, allowed_tools=["execute_command"]
        )
        assert repaired is not None
        assert repaired.tool_call["function"]["name"] == "execute_command"

    def test_repair_tool_calls_no_match(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = "This is a regular message with no tool call."
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is None

    def test_repair_tool_calls_xml_use_mcp_wrapper(
        self, repair_service: ToolCallRepairService
    ) -> None:
        content = """
        <use_mcp_tool>
            <tool_name>patch_file</tool_name>
            <tool_arguments>
                <path>src/example.py</path>
                <patch_content>
                    print("updated")
                </patch_content>
            </tool_arguments>
        </use_mcp_tool>
        """
        repaired = repair_service.repair_tool_calls(content)
        assert repaired is not None
        assert repaired.tool_call["function"]["name"] == "patch_file"
        arguments = json.loads(repaired.tool_call["function"]["arguments"])
        assert arguments["path"] == "src/example.py"
        assert 'print("updated")' in arguments["patch_content"]


class TestToolCallRepairServiceMessages:
    """Tests for repair_tool_calls_in_messages method."""

    def test_repair_tool_calls_in_messages_empty_list(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that empty message list returns empty list."""
        messages: list[dict[str, str]] = []
        repaired = repair_service.repair_tool_calls_in_messages(messages)
        assert repaired == []

    def test_repair_tool_calls_in_messages_no_assistant_messages(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that non-assistant messages are passed through unchanged."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "system", "content": "You are a helpful assistant"},
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)
        assert len(repaired) == 2
        assert repaired[0] == messages[0]
        assert repaired[1] == messages[1]

    def test_repair_tool_calls_in_messages_processes_last_assistant(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that only the last assistant message is processed."""
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "old_func", "arguments": {}}}',
            },
            {"role": "user", "content": "Continue"},
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "new_func", "arguments": {}}}',
            },
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 4
        # First assistant message should not have tool_calls added
        assert "tool_calls" not in repaired[1]
        # Last assistant message should have tool_calls added
        assert "tool_calls" in repaired[3]
        assert repaired[3]["tool_calls"][0]["function"]["name"] == "new_func"

    def test_repair_tool_calls_in_messages_skips_processed(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that messages with processing marker are skipped."""
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": '{"function_call": {"name": "test_func", "arguments": {}}}',
                "_tool_calls_processed": True,
            },
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 2
        # Message should be unchanged (no new tool_calls added)
        assert repaired[1] == messages[1]

    def test_repair_tool_calls_in_messages_xml_tool_call(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that XML tool calls are properly repaired in messages."""
        messages = [
            {
                "role": "assistant",
                "content": """
                <patch_file>
                    <path>src/example.py</path>
                    <patch_content>print("hello")</patch_content>
                </patch_file>
                """,
            },
        ]
        repaired = repair_service.repair_tool_calls_in_messages(messages)

        assert len(repaired) == 1
        assert "tool_calls" in repaired[0]
        assert repaired[0]["tool_calls"][0]["function"]["name"] == "patch_file"
        arguments = json.loads(repaired[0]["tool_calls"][0]["function"]["arguments"])
        assert arguments["path"] == "src/example.py"
