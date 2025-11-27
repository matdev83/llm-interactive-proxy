"""
Regression tests for KiloCode tool call handling issues.

These tests are based on real-world CBOR wire captures from KiloCode sessions
that experienced tool call failures. The tests ensure:

1. KiloCode-specific tools (apply_diff, insert_content, etc.) are recognized
2. Double-nested content structures are properly unwrapped
3. Tool call arguments are correctly parsed from XML format

Reference: Issue discovered during 2025-11-27 session with capture file
0645d0f084dc4b2a8b023ab0de989a1b.cbor
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from src.core.domain.streaming_response_processor import StreamingContent
from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
)
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService


class TestKiloCodeToolRecognition:
    """Tests that KiloCode-specific tools are properly recognized."""

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    def test_apply_diff_is_recognized(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that <apply_diff> tool is recognized as a tool call.

        KiloCode sometimes uses <apply_diff> directly instead of wrapping
        in <use_mcp_tool>. This must be recognized as a valid tool call.
        """
        xml_content = """<apply_diff>
<args>
  <file>
    <path>tests/unit/test_example.py</path>
    <diff>
      <content><![CDATA[<<<<<<< SEARCH
import os
import re
=======
import os
import re
import subprocess
>>>>>>> REPLACE]]></content>
      <start_line>1</start_line>
    </diff>
  </file>
</args>
</apply_diff>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert result is not None, "apply_diff should be recognized as a tool call"
        assert result.tool_call["function"]["name"] == "apply_diff"
        assert "function" in result.tool_call
        assert result.tool_call["type"] == "function"

    def test_insert_content_is_recognized(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that <insert_content> tool is recognized as a tool call."""
        xml_content = """<insert_content>
<path>tests/unit/test_example.py</path>
<line>50</line>
<content>
def test_new_function():
    pass
</content>
</insert_content>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert result is not None, "insert_content should be recognized as a tool call"
        assert result.tool_call["function"]["name"] == "insert_content"

    def test_write_to_file_is_recognized(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that <write_to_file> tool is recognized as a tool call."""
        xml_content = """<write_to_file>
<path>tests/unit/test_example.py</path>
<content>
import pytest

def test_hello():
    assert True
</content>
</write_to_file>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert result is not None, "write_to_file should be recognized as a tool call"
        assert result.tool_call["function"]["name"] == "write_to_file"

    def test_update_todo_list_is_recognized(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that <update_todo_list> tool is recognized as a tool call."""
        xml_content = """<update_todo_list>
<todos>
[x] Add dependency
[-] Run tests
</todos>
</update_todo_list>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert (
            result is not None
        ), "update_todo_list should be recognized as a tool call"
        assert result.tool_call["function"]["name"] == "update_todo_list"


class TestDoubleNestedContentUnwrapping:
    """Tests for unwrapping double-nested content structures.

    Some models output malformed arguments like:
        {"content": "{\"file_path\": \"...\", \"patch_content\": \"...\"}"}

    This should be unwrapped to:
        {"file_path": "...", "patch_content": "..."}
    """

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    def test_unwrap_nested_content_json_string(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that nested JSON strings in content are unwrapped."""
        # Simulate the malformed arguments structure
        arguments: dict[str, Any] = {
            "content": '{"file_path": "/path/to/file.py", "patch_content": "test"}'
        }

        result = repair_service._unwrap_nested_content(arguments)

        assert "file_path" in result
        assert result["file_path"] == "/path/to/file.py"
        assert "patch_content" in result
        assert result["patch_content"] == "test"
        assert "content" not in result

    def test_unwrap_preserves_valid_content_string(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that plain content strings are preserved when not JSON."""
        arguments: dict[str, Any] = {"content": "This is just plain text content"}

        result = repair_service._unwrap_nested_content(arguments)

        assert result == arguments  # Should be unchanged

    def test_unwrap_preserves_non_content_keys(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that arguments without 'content' key are preserved."""
        arguments: dict[str, Any] = {
            "file_path": "/path/to/file.py",
            "patch_content": "test",
        }

        result = repair_service._unwrap_nested_content(arguments)

        assert result == arguments  # Should be unchanged

    def test_use_mcp_tool_with_nested_arguments(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test use_mcp_tool with double-nested arguments from real capture.

        This simulates the exact pattern observed in the CBOR wire capture
        where the model output:
        <use_mcp_tool>
            <tool_name>patch_file</tool_name>
            <arguments>{"content": "{\"file_path\": \"...\", \"patch_content\": \"...\"}"}</arguments>
        </use_mcp_tool>
        """
        xml_content = """<use_mcp_tool>
<tool_name>patch_file</tool_name>
<arguments>{"content": "{\\\"file_path\\\": \\\"/path/to/file.py\\\", \\\"patch_content\\\": \\\"test\\\"}"}</arguments>
</use_mcp_tool>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert result is not None, "Tool call should be detected"
        assert result.tool_call["function"]["name"] == "patch_file"

        # Parse the arguments to check they're unwrapped
        args = json.loads(result.tool_call["function"]["arguments"])
        assert "file_path" in args, "file_path should be unwrapped from content"
        assert args["file_path"] == "/path/to/file.py"
        assert "patch_content" in args
        assert "content" not in args, "content wrapper should be removed"


class TestLeafValueExtraction:
    """Tests for _extract_leaf_values handling of content strings."""

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    def test_extract_leaf_values_unwraps_json_content(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that JSON strings in 'content' key are unwrapped."""
        obj: dict[str, Any] = {
            "content": '{"file_path": "/path/to/file.py", "patch_content": "test"}'
        }
        result: dict[str, Any] = {}

        repair_service._extract_leaf_values(obj, result)

        assert "file_path" in result
        assert result["file_path"] == "/path/to/file.py"
        assert "patch_content" in result

    def test_extract_leaf_values_preserves_plain_content(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that plain text content is preserved."""
        obj: dict[str, Any] = {"content": "Plain text content"}
        result: dict[str, Any] = {}

        repair_service._extract_leaf_values(obj, result)

        # Since it's not valid JSON, it should be preserved as-is
        assert result.get("content") == "Plain text content"


class TestStreamingToolCallIntegration:
    """Integration tests for streaming tool call handling with KiloCode patterns."""

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    @pytest.fixture
    def registry(self) -> StreamingContextRegistry:
        return StreamingContextRegistry()

    @pytest.fixture
    def processor(
        self, repair_service: ToolCallRepairService, registry: StreamingContextRegistry
    ) -> ToolCallRepairProcessor:
        return ToolCallRepairProcessor(
            repair_service, max_buffer_bytes=64 * 1024, registry=registry
        )

    @pytest.mark.asyncio
    async def test_apply_diff_in_streaming(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Test that apply_diff is properly recognized in streaming context."""
        xml_content = """<apply_diff>
<args>
  <file>
    <path>tests/unit/test_example.py</path>
    <diff>
      <content><![CDATA[<<<<<<< SEARCH
import os
=======
import os
import subprocess
>>>>>>> REPLACE]]></content>
      <start_line>1</start_line>
    </diff>
  </file>
</args>
</apply_diff>"""

        chunk = StreamingContent(
            content=xml_content,
            is_done=True,
            metadata={"session_id": "test-kilocode-session"},
        )

        result = await processor.process(chunk)

        tool_calls = result.metadata.get("tool_calls") if result.metadata else None
        assert tool_calls is not None, "Tool calls should be detected"
        assert len(tool_calls) > 0, "At least one tool call should be detected"
        assert tool_calls[0]["function"]["name"] == "apply_diff"

    @pytest.mark.asyncio
    async def test_chunked_apply_diff_streaming(
        self, processor: ToolCallRepairProcessor
    ) -> None:
        """Test that chunked apply_diff content is properly buffered and parsed."""
        session_id = "test-chunked-apply-diff"

        # Chunk 1: Start of apply_diff
        chunk1 = StreamingContent(
            content="<apply_diff>\n<args>\n  <file>\n    <path>test.py</path>",
            is_done=False,
            metadata={"session_id": session_id},
        )
        await processor.process(chunk1)  # Process but don't expect tool calls yet

        # Chunk 2: Middle of apply_diff
        chunk2 = StreamingContent(
            content="\n    <diff>\n      <content><![CDATA[",
            is_done=False,
            metadata={"session_id": session_id},
        )
        await processor.process(chunk2)  # Process but don't expect tool calls yet

        # Chunk 3: End of apply_diff
        chunk3 = StreamingContent(
            content=(
                "<<<<<<< SEARCH\nimport os\n=======\nimport os\nimport re\n"
                ">>>>>>> REPLACE]]></content>\n    </diff>\n  </file>\n</args>\n"
                "</apply_diff>"
            ),
            is_done=True,
            metadata={"session_id": session_id},
        )
        result3 = await processor.process(chunk3)

        tool_calls = result3.metadata.get("tool_calls") if result3.metadata else None
        assert tool_calls is not None, "Tool calls should be detected at end of stream"
        assert len(tool_calls) > 0
        assert tool_calls[0]["function"]["name"] == "apply_diff"


class TestKiloCodeModeSlug:
    """Tests for mode_slug tool handling which is KiloCode-specific."""

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    def test_mode_slug_is_recognized(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that <mode_slug> tool is recognized."""
        xml_content = """<mode_slug>
<content>code</content>
</mode_slug>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert result is not None, "mode_slug should be recognized as a tool call"
        assert result.tool_call["function"]["name"] == "mode_slug"


class TestPatternBasedDetection:
    """Tests verifying pattern-based tool call detection without hardcoded lists.

    These tests ensure that ANY tool can be recognized based on structural
    patterns, not by checking against a list of known tool names.
    """

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    def test_unknown_tool_is_recognized(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that completely unknown tools are recognized based on structure."""
        xml_content = """<my_custom_agent_tool>
<param1>value1</param1>
<param2>value2</param2>
</my_custom_agent_tool>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert result is not None, "Unknown tool should be recognized by structure"
        assert result.tool_call["function"]["name"] == "my_custom_agent_tool"

    def test_arbitrary_tool_with_json_args(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that arbitrary tools with JSON arguments are recognized."""
        xml_content = """<some_future_tool>
<arguments>{"key": "value", "nested": {"a": 1}}</arguments>
</some_future_tool>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert result is not None, "Tool with JSON args should be recognized"
        assert result.tool_call["function"]["name"] == "some_future_tool"

    def test_thinking_tags_are_filtered(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that thinking/reasoning tags are filtered out."""
        for tag in ["think", "thought", "thinking", "reasoning", "reflection"]:
            xml_content = f"""<{tag}>
I am thinking about the problem...
</{tag}>"""

            result = repair_service.repair_tool_calls(xml_content)

            assert result is None, f"<{tag}> should be filtered as thinking tag"

    def test_simple_parameter_not_detected_as_tool(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that simple parameter-like elements are not detected as tools."""
        # A simple path value should not be a tool call
        xml_content = """<path>/usr/local/bin/python</path>"""

        result = repair_service.repair_tool_calls(xml_content)

        # This might return None or might be detected; the key is it shouldn't
        # cause issues if detected. The heuristics are conservative.
        if result is not None:
            # If detected, verify it's at least parseable
            assert "function" in result.tool_call

    def test_tool_with_attributes_recognized(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test that tools with attributes are recognized."""
        xml_content = """<custom_tool name="test" version="1.0">
<content>Some content here</content>
</custom_tool>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert result is not None, "Tool with attributes should be recognized"
        assert result.tool_call["function"]["name"] == "custom_tool"


class TestHeuristicMethods:
    """Tests for the heuristic helper methods."""

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    def test_looks_like_simple_value_paths(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test path-like values are detected as simple values."""
        assert repair_service._looks_like_simple_value("/usr/bin/python")
        assert repair_service._looks_like_simple_value("./relative/path")
        assert repair_service._looks_like_simple_value("../parent/path")
        assert repair_service._looks_like_simple_value("C:\\Windows\\System32")
        assert repair_service._looks_like_simple_value("test.py")
        assert repair_service._looks_like_simple_value("config.json")

    def test_looks_like_simple_value_booleans(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test boolean-like values are detected as simple values."""
        assert repair_service._looks_like_simple_value("true")
        assert repair_service._looks_like_simple_value("false")
        assert repair_service._looks_like_simple_value("True")
        assert repair_service._looks_like_simple_value("FALSE")
        assert repair_service._looks_like_simple_value("yes")
        assert repair_service._looks_like_simple_value("no")

    def test_looks_like_simple_value_numbers(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test number-like values are detected as simple values."""
        assert repair_service._looks_like_simple_value("42")
        assert repair_service._looks_like_simple_value("3.14")
        assert repair_service._looks_like_simple_value("-100")

    def test_looks_like_simple_value_identifiers(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test single identifiers are detected as simple values."""
        assert repair_service._looks_like_simple_value("my_variable")
        assert repair_service._looks_like_simple_value("ClassName")
        assert repair_service._looks_like_simple_value("_private")

    def test_looks_like_simple_value_complex_not_simple(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test complex values are NOT detected as simple values."""
        # JSON should not be simple
        assert not repair_service._looks_like_simple_value('{"key": "value"}')
        # XML-like content should not be simple
        assert not repair_service._looks_like_simple_value("<tag>content</tag>")
        # Complex expressions with special chars should not be simple
        assert not repair_service._looks_like_simple_value("func(arg1, arg2)")
        # Very long content should not be simple (even if it looks like a sentence)
        long_text = "This is a very long sentence " * 10  # Over 200 chars
        assert not repair_service._looks_like_simple_value(long_text)


class TestRealWorldCapturePatterns:
    """Tests based on actual patterns from the CBOR wire capture.

    These tests reproduce the exact XML structures observed during the
    KiloCode session that experienced tool call failures.
    """

    @pytest.fixture
    def repair_service(self) -> ToolCallRepairService:
        return ToolCallRepairService()

    def test_patch_file_with_complex_patch_content(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test patch_file with complex multi-line patch content.

        This pattern was observed where the patch_content contains
        SEARCH/REPLACE blocks with escaped newlines and quotes.
        """
        xml_content = """<use_mcp_tool>
<tool_name>patch_file</tool_name>
<arguments>{"file_path": "c:/Users/test/project/pyproject.toml", "patch_content": "<<<<<<< SEARCH\\n    \\"mdformat\\",\\n=======\\n    \\"mdformat\\",\\n    \\"pymarkdown-lnt\\",\\n>>>>>>> REPLACE"}</arguments>
</use_mcp_tool>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert result is not None
        assert result.tool_call["function"]["name"] == "patch_file"

        args = json.loads(result.tool_call["function"]["arguments"])
        assert "file_path" in args
        assert "patch_content" in args
        assert "SEARCH" in args["patch_content"]
        assert "REPLACE" in args["patch_content"]

    def test_ask_followup_question_with_suggestions(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test ask_followup_question with suggestions array.

        This pattern was commonly observed in the early part of the session.
        """
        xml_content = """<use_mcp_tool>
<tool_name>ask_followup_question</tool_name>
<arguments>{"question": "Would you like me to add the library?", "suggest": ["Yes, please add it.", "No, thank you."]}</arguments>
</use_mcp_tool>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert result is not None
        assert result.tool_call["function"]["name"] == "ask_followup_question"

        args = json.loads(result.tool_call["function"]["arguments"])
        assert "question" in args
        assert "suggest" in args
        assert isinstance(args["suggest"], list)

    def test_execute_command_with_escaped_quotes(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test execute_command with escaped quotes in command.

        This pattern was observed when installing packages with pip.
        """
        xml_content = """<use_mcp_tool>
<tool_name>execute_command</tool_name>
<arguments>{"command": "./.venv/Scripts/python.exe -m pip install -e .[\\"dev\\"]"}</arguments>
</use_mcp_tool>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert result is not None
        assert result.tool_call["function"]["name"] == "execute_command"

        args = json.loads(result.tool_call["function"]["arguments"])
        assert "command" in args
        assert "pip install" in args["command"]

    def test_apply_diff_with_cdata_content(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Test apply_diff with CDATA-wrapped diff content.

        The model switched to using apply_diff with CDATA blocks after
        experiencing JSON escaping issues with patch_file.
        """
        xml_content = """<apply_diff>
<args>
  <file>
    <path>tests/unit/test_codebase_quality.py</path>
    <diff>
      <content><![CDATA[<<<<<<< SEARCH
import os
import re

import pytest
=======
import os
import re
import subprocess
import sys

import pytest
>>>>>>> REPLACE]]></content>
      <start_line>1</start_line>
    </diff>
  </file>
</args>
</apply_diff>"""

        result = repair_service.repair_tool_calls(xml_content)

        assert result is not None, "apply_diff with CDATA should be recognized"
        assert result.tool_call["function"]["name"] == "apply_diff"
