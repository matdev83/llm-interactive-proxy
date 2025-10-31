"""Tests for ZAI Coding Plan MCP tool call extraction."""

import json

import pytest
from src.connectors.zai_coding_plan import ZaiCodingPlanBackend


class TestZaiMCPToolExtraction:
    """Test MCP tool call extraction from message content."""

    @pytest.fixture
    def backend(self):
        """Create a minimal backend instance for testing."""

        # We only need the method, not a fully initialized backend
        class MockBackend:
            def _extract_mcp_tool_calls_from_messages(self, messages):
                # Use the actual implementation
                backend = ZaiCodingPlanBackend.__new__(ZaiCodingPlanBackend)
                return backend._extract_mcp_tool_calls_from_messages(messages)

        return MockBackend()

    def test_extract_single_mcp_tool_call(self, backend):
        """Test extracting a single MCP tool call from message content."""
        messages = [
            {
                "role": "assistant",
                "content": 'I will use the patch_file tool.\n\n<use_mcp_tool tool_name="patch_file"><path>test.py</path><content>new content</content></use_mcp_tool>',
            }
        ]

        result = backend._extract_mcp_tool_calls_from_messages(messages)

        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        assert "tool_calls" in result[0]
        assert len(result[0]["tool_calls"]) == 1

        tool_call = result[0]["tool_calls"][0]
        assert tool_call["type"] == "function"
        assert tool_call["function"]["name"] == "patch_file"

        args = json.loads(tool_call["function"]["arguments"])
        assert args["path"] == "test.py"
        assert args["content"] == "new content"

        # XML should be removed from content
        assert "<use_mcp_tool" not in result[0]["content"]

    def test_extract_multiple_mcp_tool_calls(self, backend):
        """Test extracting multiple MCP tool calls from message content."""
        messages = [
            {
                "role": "assistant",
                "content": '<use_mcp_tool tool_name="read_file"><path>file1.py</path></use_mcp_tool>\n\n<use_mcp_tool tool_name="read_file"><path>file2.py</path></use_mcp_tool>',
            }
        ]

        result = backend._extract_mcp_tool_calls_from_messages(messages)

        assert len(result) == 1
        assert "tool_calls" in result[0]
        assert len(result[0]["tool_calls"]) == 2

        assert result[0]["tool_calls"][0]["function"]["name"] == "read_file"
        assert result[0]["tool_calls"][1]["function"]["name"] == "read_file"

    def test_extract_mcp_tool_call_with_name_attribute(self, backend):
        """Tool extraction should handle name attribute variant."""
        messages = [
            {
                "role": "assistant",
                "content": '<use_mcp_tool name="patch_file"><tool_arguments><path>main.py</path><diff>diff-content</diff></tool_arguments></use_mcp_tool>',
            }
        ]

        result = backend._extract_mcp_tool_calls_from_messages(messages)

        assert len(result) == 1
        tool_calls = result[0]["tool_calls"]
        assert len(tool_calls) == 1
        call = tool_calls[0]
        assert call["function"]["name"] == "patch_file"
        args = json.loads(call["function"]["arguments"])
        assert args["path"] == "main.py"
        assert args["diff"] == "diff-content"

    def test_extract_direct_patch_file_nested_structure(self, backend):
        """Direct <patch_file> XML should be converted into a tool call."""
        messages = [
            {
                "role": "assistant",
                "content": """
                Here is the fix:
                <patch_file>
                    <args>
                        <file>
                            <path>src/app.py</path>
                            <diff>
                                <content><![CDATA[
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old
+new
]]></content>
                            </diff>
                        </file>
                    </args>
                </patch_file>
                """,
            }
        ]

        result = backend._extract_mcp_tool_calls_from_messages(messages)

        assert len(result) == 1
        tool_calls = result[0].get("tool_calls", [])
        assert len(tool_calls) == 1
        call = tool_calls[0]
        assert call["function"]["name"] == "patch_file"
        args = json.loads(call["function"]["arguments"])
        assert args["path"] == "src/app.py"
        assert "diff" in args
        assert "+new" in args["diff"]

    def test_extract_generic_direct_tool(self, backend):
        """Generic direct XML tool invocations should be converted."""
        messages = [
            {
                "role": "assistant",
                "content": """
                <list_files>
                    <path>src</path>
                    <recursive>true</recursive>
                </list_files>
                """,
            }
        ]

        result = backend._extract_mcp_tool_calls_from_messages(messages)

        assert len(result) == 1
        tool_calls = result[0].get("tool_calls", [])
        assert len(tool_calls) == 1
        call = tool_calls[0]
        assert call["function"]["name"] == "list_files"
        args = json.loads(call["function"]["arguments"])
        assert args["path"] == "src"
        assert args["recursive"] == "true"

    def test_preserve_non_assistant_messages(self, backend):
        """Test that non-assistant messages are not modified."""
        messages = [
            {"role": "user", "content": "Hello"},
            {
                "role": "assistant",
                "content": '<use_mcp_tool tool_name="test"><arg>value</arg></use_mcp_tool>',
            },
            {"role": "user", "content": "Thanks"},
        ]

        result = backend._extract_mcp_tool_calls_from_messages(messages)

        assert len(result) == 3
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "Hello"
        assert "tool_calls" not in result[0]

        assert result[2]["role"] == "user"
        assert result[2]["content"] == "Thanks"
        assert "tool_calls" not in result[2]

    def test_preserve_existing_tool_calls(self, backend):
        """Test that existing tool_calls are not overwritten."""
        existing_tool_call = {
            "id": "call_123",
            "type": "function",
            "function": {"name": "existing_tool", "arguments": "{}"},
        }

        messages = [
            {
                "role": "assistant",
                "content": '<use_mcp_tool tool_name="new_tool"><arg>value</arg></use_mcp_tool>',
                "tool_calls": [existing_tool_call],
            }
        ]

        result = backend._extract_mcp_tool_calls_from_messages(messages)

        assert len(result) == 1
        # Should preserve existing tool_calls, not extract new ones
        assert result[0]["tool_calls"] == [existing_tool_call]

    def test_no_mcp_tools_in_content(self, backend):
        """Test messages without MCP tool calls are unchanged."""
        messages = [
            {"role": "assistant", "content": "Just a regular response"},
            {"role": "user", "content": "Another message"},
        ]

        result = backend._extract_mcp_tool_calls_from_messages(messages)

        assert len(result) == 2
        assert result[0] == messages[0]
        assert result[1] == messages[1]

    def test_preserve_remaining_content(self, backend):
        """Test that non-XML content is preserved after extraction."""
        messages = [
            {
                "role": "assistant",
                "content": 'I will patch the file.\n\n<use_mcp_tool tool_name="patch_file"><path>test.py</path></use_mcp_tool>\n\nThis should fix the issue.',
            }
        ]

        result = backend._extract_mcp_tool_calls_from_messages(messages)

        assert len(result) == 1
        assert "tool_calls" in result[0]
        # Should preserve text before and after XML
        content = result[0]["content"]
        assert "I will patch the file." in content
        assert "This should fix the issue." in content
        assert "<use_mcp_tool" not in content

    def test_empty_content_after_extraction(self, backend):
        """Test that empty content is set to empty string after extraction."""
        messages = [
            {
                "role": "assistant",
                "content": '<use_mcp_tool tool_name="test"><arg>value</arg></use_mcp_tool>',
            }
        ]

        result = backend._extract_mcp_tool_calls_from_messages(messages)

        assert len(result) == 1
        assert result[0]["content"] == ""
        assert "tool_calls" in result[0]

    def test_complex_nested_arguments(self, backend):
        """Test extraction of complex nested XML arguments."""
        messages = [
            {
                "role": "assistant",
                "content": '<use_mcp_tool tool_name="patch_file"><path>src/main.py</path><diff>--- a/src/main.py\n+++ b/src/main.py\n@@ -1,3 +1,3 @@\n-old line\n+new line</diff></use_mcp_tool>',
            }
        ]

        result = backend._extract_mcp_tool_calls_from_messages(messages)

        assert len(result) == 1
        tool_call = result[0]["tool_calls"][0]
        args = json.loads(tool_call["function"]["arguments"])

        assert args["path"] == "src/main.py"
        assert "diff" in args
        assert "old line" in args["diff"]
        assert "new line" in args["diff"]
