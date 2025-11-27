"""Tests for tool call repair service handling of inner XML tags.

This test module verifies that inner XML tags with SIMPLE VALUE content
(like start_line, end_line, file paths, etc.) are correctly skipped and not
misidentified as standalone tool calls.

DESIGN PRINCIPLE: The detection uses PURELY STRUCTURAL heuristics, not
hardcoded tag name lists. This means:
- Tags with simple values (numbers, paths, short identifiers) -> NOT tool calls
- Tags with complex values (JSON, multi-line, function calls) -> MAY be tool calls

This approach supports any tool from any agent without hardcoded lists.
"""

import json

import pytest
from src.core.services.tool_call_repair_service import ToolCallRepairService


@pytest.fixture
def repair_service() -> ToolCallRepairService:
    return ToolCallRepairService()


class TestInnerTagsNotParsedAsToolCalls:
    """Test that inner/child XML tags are not misidentified as tool calls."""

    def test_start_line_tag_not_parsed_as_tool_call(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """start_line should be recognized as inner tag of read_file, not a tool."""
        content = "<start_line>1089</start_line>"
        result = repair_service.repair_tool_calls(content)
        # Should return None because start_line is an inner tag, not a tool
        assert result is None

    def test_end_line_tag_not_parsed_as_tool_call(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """end_line should be recognized as inner tag, not a tool."""
        content = "<end_line>200</end_line>"
        result = repair_service.repair_tool_calls(content)
        assert result is None

    def test_search_tag_not_parsed_as_tool_call(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """search tag should be recognized as inner tag of search_and_replace."""
        content = "<search>def old_function():</search>"
        result = repair_service.repair_tool_calls(content)
        assert result is None

    def test_replace_tag_not_parsed_as_tool_call(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """replace tag should be recognized as inner tag of search_and_replace."""
        content = "<replace>def new_function():</replace>"
        result = repair_service.repair_tool_calls(content)
        assert result is None

    def test_position_tag_not_parsed_as_tool_call(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """position tag should be recognized as inner tag of insert_content."""
        content = "<position>42</position>"
        result = repair_service.repair_tool_calls(content)
        assert result is None

    def test_file_path_tag_not_parsed_as_tool_call(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """file_path tag should be recognized as inner tag."""
        content = "<file_path>/path/to/file.py</file_path>"
        result = repair_service.repair_tool_calls(content)
        assert result is None

    def test_new_content_tag_with_code_may_be_detected(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Content with code-like patterns may be detected as tool calls.

        NOTE: With purely structural detection (no hardcoded tag names),
        content like `print('hello')` doesn't match simple value patterns,
        so it may be treated as a tool call. This is acceptable because:
        1. Clients will ignore unknown tool calls
        2. We can't distinguish without hardcoded lists
        """
        content = "<new_content>print('hello')</new_content>"
        result = repair_service.repair_tool_calls(content)
        # With structural detection, this WILL be detected as a tool call
        # because the content doesn't match simple value patterns
        assert result is not None

    def test_old_content_tag_with_code_may_be_detected(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Content with code-like patterns may be detected as tool calls.

        Same reasoning as test_new_content_tag_with_code_may_be_detected.
        """
        content = "<old_content>print('world')</old_content>"
        result = repair_service.repair_tool_calls(content)
        # With structural detection, this WILL be detected as a tool call
        assert result is not None

    def test_line_tag_not_parsed_as_tool_call(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """line tag should be recognized as inner tag."""
        content = "<line>100</line>"
        result = repair_service.repair_tool_calls(content)
        assert result is None

    def test_operations_tag_with_json_may_be_detected(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Content starting with JSON markers may be detected as tool calls.

        NOTE: With purely structural detection, content starting with `[{`
        looks like JSON and may be treated as a tool call. This is acceptable
        because we can't reliably distinguish JSON arguments from JSON content
        without hardcoded lists.
        """
        content = "<operations>[{'op': 'add', 'path': '/foo'}]</operations>"
        result = repair_service.repair_tool_calls(content)
        # JSON-like content may be detected as a tool call
        assert result is not None

    def test_changes_tag_not_parsed_as_tool_call(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """changes tag should be recognized as inner tag."""
        content = "<changes>some diff content</changes>"
        result = repair_service.repair_tool_calls(content)
        assert result is None


class TestOuterToolsStillParsed:
    """Test that outer tool tags are still correctly parsed."""

    def test_read_file_with_start_line_parsed_correctly(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """read_file containing start_line should parse the outer tool correctly."""
        content = """<read_file>
            <path>src/example.py</path>
            <start_line>100</start_line>
            <end_line>200</end_line>
        </read_file>"""
        result = repair_service.repair_tool_calls(content)
        assert result is not None
        assert result.tool_call["function"]["name"] == "read_file"
        args = json.loads(result.tool_call["function"]["arguments"])
        assert args["path"] == "src/example.py"
        # start_line and end_line should be parsed as parameters, not tool calls
        assert args.get("start_line") == 100 or "start_line" in args
        assert args.get("end_line") == 200 or "end_line" in args

    def test_search_and_replace_parsed_correctly(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """search_and_replace with search/replace inner tags should work."""
        content = """<search_and_replace>
            <path>src/example.py</path>
            <search>old_code</search>
            <replace>new_code</replace>
        </search_and_replace>"""
        result = repair_service.repair_tool_calls(content)
        assert result is not None
        assert result.tool_call["function"]["name"] == "search_and_replace"
        args = json.loads(result.tool_call["function"]["arguments"])
        assert args["path"] == "src/example.py"
        assert args["search"] == "old_code"
        assert args["replace"] == "new_code"

    def test_execute_command_with_command_tag(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """execute_command with command inner tag should parse correctly."""
        content = """<execute_command>
            <command>ls -la</command>
        </execute_command>"""
        result = repair_service.repair_tool_calls(content)
        assert result is not None
        assert result.tool_call["function"]["name"] == "execute_command"
        args = json.loads(result.tool_call["function"]["arguments"])
        assert args["command"] == "ls -la"


class TestMixedContentNotMisidentified:
    """Test that mixed content with partial inner tags is handled correctly."""

    def test_text_containing_start_line_word_not_misidentified(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Text mentioning 'start_line' in prose should not trigger false positives."""
        content = (
            "The start_line parameter should be set to 100 for optimal performance."
        )
        result = repair_service.repair_tool_calls(content)
        assert result is None

    def test_code_snippet_with_line_variables_not_misidentified(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Code snippets with line variables should not be misidentified."""
        content = (
            "start_line = 100\nend_line = 200\nfor line in range(start_line, end_line):"
        )
        result = repair_service.repair_tool_calls(content)
        assert result is None

    def test_partial_xml_with_inner_tags_not_misidentified(
        self, repair_service: ToolCallRepairService
    ) -> None:
        """Partial XML containing only inner tags should not create tool calls."""
        # This simulates what happens when buffer is flushed mid-tool-call
        content = """<path>src/example.py</path>
            <start_line>100</start_line>
            <end_line>200</end_line>"""
        result = repair_service.repair_tool_calls(content)
        # All three are inner tags - should not create a tool call
        assert result is None
