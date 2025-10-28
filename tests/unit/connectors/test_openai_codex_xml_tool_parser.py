"""Unit tests for OpenAI Codex XMLToolParser."""

import pytest
from src.connectors._openai_codex_xml_tool_parser import (
    XMLParseError,
    XMLToolParser,
)


class TestXMLToolParserReadFile:
    """Test parsing <read_file> tags."""

    def test_parse_read_file_simple_path(self):
        """Test parsing read_file with simple path content."""
        parser = XMLToolParser()
        xml = "<read_file>src/main.py</read_file>"

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "read_file"
        assert result.original_tag == "read_file"
        assert result.arguments["path"] == "src/main.py"
        assert result.command_text is None

    def test_parse_read_file_with_path_attribute(self):
        """Test parsing read_file with path as attribute."""
        parser = XMLToolParser()
        xml = '<read_file path="config/settings.yaml" />'

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["path"] == "config/settings.yaml"

    def test_parse_read_file_with_nested_path_tag(self):
        """Test parsing read_file with nested <path> tag."""
        parser = XMLToolParser()
        xml = "<read_file><path>tests/test_file.py</path></read_file>"

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["path"] == "tests/test_file.py"

    def test_parse_read_file_with_line_range(self):
        """Test parsing read_file with start_line and end_line."""
        parser = XMLToolParser()
        xml = """<read_file>
            <path>src/utils.py</path>
            <start_line>10</start_line>
            <end_line>20</end_line>
        </read_file>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["path"] == "src/utils.py"
        assert result.arguments["start_line"] == 10
        assert result.arguments["end_line"] == 20

    def test_parse_read_file_missing_path_raises_error(self):
        """Test that missing path raises XMLParseError."""
        parser = XMLToolParser()
        xml = "<read_file></read_file>"

        with pytest.raises(XMLParseError) as exc_info:
            parser.parse(xml)

        assert "Missing required 'path' parameter" in str(exc_info.value)

    def test_parse_read_file_invalid_line_number_raises_error(self):
        """Test that invalid line number raises XMLParseError."""
        parser = XMLToolParser()
        xml = """<read_file>
            <path>src/main.py</path>
            <start_line>not_a_number</start_line>
        </read_file>"""

        with pytest.raises(XMLParseError) as exc_info:
            parser.parse(xml)

        assert "Invalid start_line value" in str(exc_info.value)


class TestXMLToolParserListFiles:
    """Test parsing <list_files> tags."""

    def test_parse_list_files_simple_path(self):
        """Test parsing list_files with simple path."""
        parser = XMLToolParser()
        xml = "<list_files>src/</list_files>"

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "list_files"
        assert result.arguments["path"] == "src/"

    def test_parse_list_files_default_path(self):
        """Test parsing list_files with no path defaults to current directory."""
        parser = XMLToolParser()
        xml = "<list_files></list_files>"

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["path"] == "."

    def test_parse_list_files_with_recursive_attribute(self):
        """Test parsing list_files with recursive attribute."""
        parser = XMLToolParser()
        xml = '<list_files path="src/" recursive="true" />'

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["path"] == "src/"
        assert result.arguments["recursive"] is True

    def test_parse_list_files_with_recursive_false(self):
        """Test parsing list_files with recursive=false."""
        parser = XMLToolParser()
        xml = '<list_files path="src/" recursive="false" />'

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["recursive"] is False

    def test_parse_list_files_with_nested_recursive_tag(self):
        """Test parsing list_files with nested <recursive> tag."""
        parser = XMLToolParser()
        xml = """<list_files>
            <path>tests/</path>
            <recursive>yes</recursive>
        </list_files>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["path"] == "tests/"
        assert result.arguments["recursive"] is True

    def test_parse_list_files_with_depth(self):
        """Test parsing list_files with depth parameter."""
        parser = XMLToolParser()
        xml = """<list_files>
            <path>src/</path>
            <depth>2</depth>
        </list_files>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["depth"] == 2

    def test_parse_list_files_invalid_depth_raises_error(self):
        """Test that invalid depth raises XMLParseError."""
        parser = XMLToolParser()
        xml = """<list_files>
            <path>src/</path>
            <depth>invalid</depth>
        </list_files>"""

        with pytest.raises(XMLParseError) as exc_info:
            parser.parse(xml)

        assert "Invalid depth value" in str(exc_info.value)


class TestXMLToolParserExecuteCommand:
    """Test parsing <execute_command> tags."""

    def test_parse_execute_command_simple(self):
        """Test parsing execute_command with simple command."""
        parser = XMLToolParser()
        xml = "<execute_command>ls -la</execute_command>"

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "execute_command"
        assert result.arguments["command"] == "ls -la"
        assert result.command_text == "ls -la"

    def test_parse_execute_command_with_command_attribute(self):
        """Test parsing execute_command with command as attribute."""
        parser = XMLToolParser()
        xml = '<execute_command command="npm test" />'

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["command"] == "npm test"
        assert result.command_text == "npm test"

    def test_parse_execute_command_with_nested_command_tag(self):
        """Test parsing execute_command with nested <command> tag."""
        parser = XMLToolParser()
        xml = "<execute_command><command>python test.py</command></execute_command>"

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["command"] == "python test.py"

    def test_parse_execute_command_with_working_dir(self):
        """Test parsing execute_command with working directory."""
        parser = XMLToolParser()
        xml = """<execute_command>
            <command>make build</command>
            <working_dir>/tmp/project</working_dir>
        </execute_command>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["command"] == "make build"
        assert result.arguments["working_dir"] == "/tmp/project"

    def test_parse_execute_command_with_timeout(self):
        """Test parsing execute_command with timeout."""
        parser = XMLToolParser()
        xml = '<execute_command command="long_task.sh" timeout="300" />'

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["timeout"] == 300

    def test_parse_execute_command_missing_command_raises_error(self):
        """Test that missing command raises XMLParseError."""
        parser = XMLToolParser()
        xml = "<execute_command></execute_command>"

        with pytest.raises(XMLParseError) as exc_info:
            parser.parse(xml)

        assert "Missing required 'command' parameter" in str(exc_info.value)

    def test_parse_execute_command_invalid_timeout_raises_error(self):
        """Test that invalid timeout raises XMLParseError."""
        parser = XMLToolParser()
        xml = '<execute_command command="test" timeout="invalid" />'

        with pytest.raises(XMLParseError) as exc_info:
            parser.parse(xml)

        assert "Invalid timeout value" in str(exc_info.value)


class TestXMLToolParserSearch:
    """Test parsing <codebase_search> and <search_files> tags."""

    def test_parse_codebase_search_simple(self):
        """Test parsing codebase_search with simple query."""
        parser = XMLToolParser()
        xml = "<codebase_search>def main</codebase_search>"

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "codebase_search"
        assert result.arguments["query"] == "def main"

    def test_parse_search_files_with_pattern(self):
        """Test parsing search_files with pattern."""
        parser = XMLToolParser()
        xml = '<search_files query="import os" pattern="*.py" />'

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "search_files"
        assert result.arguments["query"] == "import os"
        assert result.arguments["pattern"] == "*.py"

    def test_parse_search_with_include_exclude(self):
        """Test parsing search with include and exclude patterns."""
        parser = XMLToolParser()
        xml = """<codebase_search>
            <query>TODO</query>
            <include>src/**/*.py</include>
            <exclude>tests/**</exclude>
        </codebase_search>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["query"] == "TODO"
        assert result.arguments["include"] == "src/**/*.py"
        assert result.arguments["exclude"] == "tests/**"

    def test_parse_search_with_recursive(self):
        """Test parsing search with recursive flag."""
        parser = XMLToolParser()
        xml = '<search_files query="class" recursive="true" />'

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["recursive"] is True

    def test_parse_search_missing_query_raises_error(self):
        """Test that missing query raises XMLParseError."""
        parser = XMLToolParser()
        xml = "<codebase_search></codebase_search>"

        with pytest.raises(XMLParseError) as exc_info:
            parser.parse(xml)

        assert "Missing required 'query' parameter" in str(exc_info.value)


class TestXMLToolParserMCPTools:
    """Test parsing <use_mcp_tool> and <access_mcp_resource> tags."""

    def test_parse_use_mcp_tool_with_name(self):
        """Test parsing use_mcp_tool with tool name."""
        parser = XMLToolParser()
        xml = '<use_mcp_tool name="patch_file"></use_mcp_tool>'

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "use_mcp_tool"
        assert result.arguments["tool_name"] == "patch_file"
        assert result.arguments["tool_arguments"] == {}

    def test_parse_use_mcp_tool_with_nested_name(self):
        """Test parsing use_mcp_tool with nested <name> tag."""
        parser = XMLToolParser()
        xml = "<use_mcp_tool><name>custom_tool</name></use_mcp_tool>"

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["tool_name"] == "custom_tool"

    def test_parse_use_mcp_tool_with_arguments(self):
        """Test parsing use_mcp_tool with nested arguments."""
        parser = XMLToolParser()
        xml = """<use_mcp_tool name="patch_file">
            <arguments>
                <diff>--- a/file.py\n+++ b/file.py</diff>
                <path>src/file.py</path>
            </arguments>
        </use_mcp_tool>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["tool_name"] == "patch_file"
        assert "diff" in result.arguments["tool_arguments"]
        assert "path" in result.arguments["tool_arguments"]

    def test_parse_use_mcp_tool_missing_name_raises_error(self):
        """Test that missing tool name raises XMLParseError."""
        parser = XMLToolParser()
        xml = "<use_mcp_tool></use_mcp_tool>"

        with pytest.raises(XMLParseError) as exc_info:
            parser.parse(xml)

        assert "Missing required 'name' parameter" in str(exc_info.value)

    def test_parse_access_mcp_resource_with_uri(self):
        """Test parsing access_mcp_resource with URI."""
        parser = XMLToolParser()
        xml = '<access_mcp_resource uri="file://path/to/resource" />'

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "access_mcp_resource"
        assert result.arguments["uri"] == "file://path/to/resource"

    def test_parse_access_mcp_resource_with_nested_uri(self):
        """Test parsing access_mcp_resource with nested <uri> tag."""
        parser = XMLToolParser()
        xml = "<access_mcp_resource><uri>http://example.com/api</uri></access_mcp_resource>"

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["uri"] == "http://example.com/api"

    def test_parse_access_mcp_resource_simple_content(self):
        """Test parsing access_mcp_resource with simple content."""
        parser = XMLToolParser()
        xml = "<access_mcp_resource>file://data.json</access_mcp_resource>"

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["uri"] == "file://data.json"

    def test_parse_access_mcp_resource_missing_uri_raises_error(self):
        """Test that missing URI raises XMLParseError."""
        parser = XMLToolParser()
        xml = "<access_mcp_resource></access_mcp_resource>"

        with pytest.raises(XMLParseError) as exc_info:
            parser.parse(xml)

        assert "Missing required 'uri' parameter" in str(exc_info.value)


class TestXMLToolParserConversationControl:
    """Test parsing <attempt_completion> and <ask_followup_question> tags."""

    def test_parse_attempt_completion_with_result(self):
        """Test parsing attempt_completion with result."""
        parser = XMLToolParser()
        xml = """<attempt_completion>
            <result>Task completed successfully</result>
        </attempt_completion>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "attempt_completion"
        assert result.arguments["result"] == "Task completed successfully"

    def test_parse_attempt_completion_simple_content(self):
        """Test parsing attempt_completion with simple content."""
        parser = XMLToolParser()
        xml = "<attempt_completion>All tests passed</attempt_completion>"

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["result"] == "All tests passed"

    def test_parse_attempt_completion_empty(self):
        """Test parsing attempt_completion with no content."""
        parser = XMLToolParser()
        xml = "<attempt_completion></attempt_completion>"

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["result"] == ""

    def test_parse_ask_followup_question_simple(self):
        """Test parsing ask_followup_question with simple question."""
        parser = XMLToolParser()
        xml = "<ask_followup_question>What should I do next?</ask_followup_question>"

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "ask_followup_question"
        assert result.arguments["question"] == "What should I do next?"

    def test_parse_ask_followup_question_with_nested_tag(self):
        """Test parsing ask_followup_question with nested <question> tag."""
        parser = XMLToolParser()
        xml = """<ask_followup_question>
            <question>Should I proceed with deployment?</question>
        </ask_followup_question>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["question"] == "Should I proceed with deployment?"

    def test_parse_ask_followup_question_missing_question_raises_error(self):
        """Test that missing question raises XMLParseError."""
        parser = XMLToolParser()
        xml = "<ask_followup_question></ask_followup_question>"

        with pytest.raises(XMLParseError) as exc_info:
            parser.parse(xml)

        assert "Missing required 'question' parameter" in str(exc_info.value)


class TestXMLToolParserEditingTools:
    """Test parsing editing tool tags."""

    def test_parse_search_and_replace(self):
        """Test parsing search_and_replace tag."""
        parser = XMLToolParser()
        xml = """<search_and_replace>
            <path>src/main.py</path>
            <search>old_function</search>
            <replace>new_function</replace>
        </search_and_replace>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "search_and_replace"
        assert result.arguments["path"] == "src/main.py"
        assert result.arguments["search"] == "old_function"
        assert result.arguments["replace"] == "new_function"

    def test_parse_search_and_replace_missing_path_raises_error(self):
        """Test that missing path in search_and_replace raises error."""
        parser = XMLToolParser()
        xml = """<search_and_replace>
            <search>old</search>
            <replace>new</replace>
        </search_and_replace>"""

        with pytest.raises(XMLParseError) as exc_info:
            parser.parse(xml)

        assert "Missing required 'path' parameter" in str(exc_info.value)

    def test_parse_write_to_file(self):
        """Test parsing write_to_file tag."""
        parser = XMLToolParser()
        xml = """<write_to_file>
            <path>output.txt</path>
            <content>Hello, World!</content>
        </write_to_file>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "write_to_file"
        assert result.arguments["path"] == "output.txt"
        assert result.arguments["content"] == "Hello, World!"

    def test_parse_write_to_file_missing_content_raises_error(self):
        """Test that missing content in write_to_file raises error."""
        parser = XMLToolParser()
        xml = """<write_to_file>
            <path>output.txt</path>
        </write_to_file>"""

        with pytest.raises(XMLParseError) as exc_info:
            parser.parse(xml)

        assert "Missing required 'content' parameter" in str(exc_info.value)

    def test_parse_insert_content(self):
        """Test parsing insert_content tag."""
        parser = XMLToolParser()
        xml = """<insert_content>
            <path>file.py</path>
            <content>new line</content>
            <position>10</position>
        </insert_content>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "insert_content"
        assert result.arguments["path"] == "file.py"
        assert result.arguments["content"] == "new line"
        assert result.arguments["position"] == 10

    def test_parse_insert_content_invalid_position_raises_error(self):
        """Test that invalid position in insert_content raises error."""
        parser = XMLToolParser()
        xml = """<insert_content>
            <path>file.py</path>
            <content>text</content>
            <position>invalid</position>
        </insert_content>"""

        with pytest.raises(XMLParseError) as exc_info:
            parser.parse(xml)

        assert "Invalid position value" in str(exc_info.value)

    def test_parse_edit_file(self):
        """Test parsing edit_file tag."""
        parser = XMLToolParser()
        xml = """<edit_file>
            <path>config.yaml</path>
            <content>new config</content>
        </edit_file>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "edit_file"
        assert result.arguments["path"] == "config.yaml"
        assert result.arguments["content"] == "new config"


class TestXMLToolParserExtractTagContent:
    """Test extract_tag_content method."""

    def test_extract_tag_content_basic(self):
        """Test extracting content from basic tag."""
        parser = XMLToolParser()
        xml = "<tag>content here</tag>"

        content = parser.extract_tag_content(xml, "tag")

        assert content == "content here"

    def test_extract_tag_content_with_whitespace(self):
        """Test extracting content with whitespace."""
        parser = XMLToolParser()
        xml = "<tag>  content with spaces  </tag>"

        content = parser.extract_tag_content(xml, "tag")

        assert content == "content with spaces"

    def test_extract_tag_content_multiline(self):
        """Test extracting multiline content."""
        parser = XMLToolParser()
        xml = """<tag>
            line 1
            line 2
        </tag>"""

        content = parser.extract_tag_content(xml, "tag")

        assert "line 1" in content
        assert "line 2" in content

    def test_extract_tag_content_case_insensitive(self):
        """Test that tag extraction is case-insensitive."""
        parser = XMLToolParser()
        xml = "<TAG>content</TAG>"

        content = parser.extract_tag_content(xml, "tag")

        assert content == "content"

    def test_extract_tag_content_with_attributes(self):
        """Test extracting content from tag with attributes."""
        parser = XMLToolParser()
        xml = '<tag attr="value">content</tag>'

        content = parser.extract_tag_content(xml, "tag")

        assert content == "content"

    def test_extract_tag_content_self_closing(self):
        """Test extracting from self-closing tag."""
        parser = XMLToolParser()
        xml = '<tag attr="value" />'

        content = parser.extract_tag_content(xml, "tag")

        assert content == ""

    def test_extract_tag_content_not_found(self):
        """Test that None is returned when tag not found."""
        parser = XMLToolParser()
        xml = "<other>content</other>"

        content = parser.extract_tag_content(xml, "tag")

        assert content is None

    def test_extract_tag_content_empty_input(self):
        """Test that None is returned for empty input."""
        parser = XMLToolParser()

        content = parser.extract_tag_content("", "tag")

        assert content is None


class TestXMLToolParserSpecialCharacters:
    """Test handling of special characters in XML content."""

    def test_parse_with_ampersand(self):
        """Test parsing content with ampersand."""
        parser = XMLToolParser()
        xml = "<execute_command>echo 'A &amp; B'</execute_command>"

        result = parser.parse(xml)

        assert result is not None
        assert "A &amp; B" in result.arguments["command"]

    def test_parse_with_quotes(self):
        """Test parsing content with quotes."""
        parser = XMLToolParser()
        xml = '<execute_command>echo "Hello World"</execute_command>'

        result = parser.parse(xml)

        assert result is not None
        assert '"Hello World"' in result.arguments["command"]

    def test_parse_with_less_than_greater_than(self):
        """Test parsing content with < and > characters."""
        parser = XMLToolParser()
        xml = "<codebase_search>if x &lt; 10 and y &gt; 5</codebase_search>"

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["query"] == "if x &lt; 10 and y &gt; 5"

    def test_parse_with_newlines(self):
        """Test parsing content with newlines."""
        parser = XMLToolParser()
        xml = """<write_to_file>
            <path>test.txt</path>
            <content>Line 1
Line 2
Line 3</content>
        </write_to_file>"""

        result = parser.parse(xml)

        assert result is not None
        assert "Line 1" in result.arguments["content"]
        assert "Line 2" in result.arguments["content"]

    def test_parse_with_special_path_characters(self):
        """Test parsing paths with special characters."""
        parser = XMLToolParser()
        xml = "<read_file>path/to/file-name_v2.0.py</read_file>"

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["path"] == "path/to/file-name_v2.0.py"


class TestXMLToolParserMalformedXML:
    """Test error handling for malformed XML."""

    def test_parse_unclosed_tag(self):
        """Test that unclosed tag returns None (not found)."""
        parser = XMLToolParser()
        xml = "<read_file>path/to/file.py"

        result = parser.parse(xml)

        # Should not find the tag since it's not properly closed
        assert result is None

    def test_parse_mismatched_tags(self):
        """Test that mismatched tags return None."""
        parser = XMLToolParser()
        xml = "<read_file>content</list_files>"

        result = parser.parse(xml)

        # Should not match either tag
        assert result is None

    def test_parse_empty_string(self):
        """Test that empty string returns None."""
        parser = XMLToolParser()

        result = parser.parse("")

        assert result is None

    def test_parse_none_input(self):
        """Test that None input returns None."""
        parser = XMLToolParser()

        result = parser.parse(None)  # type: ignore

        assert result is None

    def test_parse_non_xml_content(self):
        """Test that non-XML content returns None."""
        parser = XMLToolParser()
        xml = "This is just plain text without any XML tags"

        result = parser.parse(xml)

        assert result is None


class TestXMLToolParserNestedParameters:
    """Test extraction of nested parameters."""

    def test_parse_nested_parameters_in_use_mcp_tool(self):
        """Test parsing nested parameters in use_mcp_tool."""
        parser = XMLToolParser()
        xml = """<use_mcp_tool name="complex_tool">
            <arguments>
                <param1>value1</param1>
                <param2>value2</param2>
                <nested>
                    <sub_param>sub_value</sub_param>
                </nested>
            </arguments>
        </use_mcp_tool>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["tool_arguments"]["param1"] == "value1"
        assert result.arguments["tool_arguments"]["param2"] == "value2"

    def test_parse_multiple_nested_tags(self):
        """Test parsing multiple nested tags."""
        parser = XMLToolParser()
        xml = """<search_and_replace>
            <path>src/main.py</path>
            <search>old_value</search>
            <replace>new_value</replace>
        </search_and_replace>"""

        result = parser.parse(xml)

        assert result is not None
        assert len(result.arguments) == 3
        assert all(key in result.arguments for key in ["path", "search", "replace"])


class TestXMLToolParserCaseInsensitivity:
    """Test case-insensitive tag matching."""

    def test_parse_uppercase_tag(self):
        """Test parsing uppercase tag name."""
        parser = XMLToolParser()
        xml = "<READ_FILE>src/main.py</READ_FILE>"

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "read_file"

    def test_parse_mixed_case_tag(self):
        """Test parsing mixed case tag name."""
        parser = XMLToolParser()
        xml = "<Execute_Command>ls -la</Execute_Command>"

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "execute_command"

    def test_parse_mixed_case_nested_tags(self):
        """Test parsing mixed case nested tags."""
        parser = XMLToolParser()
        xml = """<read_file>
            <PATH>src/utils.py</PATH>
            <Start_Line>5</Start_Line>
        </read_file>"""

        result = parser.parse(xml)

        assert result is not None
        assert result.arguments["path"] == "src/utils.py"
        assert result.arguments["start_line"] == 5


class TestXMLToolParserUnsupportedTags:
    """Test handling of unsupported tags."""

    def test_parse_unsupported_tag_returns_none(self):
        """Test that unsupported tags return None."""
        parser = XMLToolParser()
        xml = "<unsupported_tool>some content</unsupported_tool>"

        result = parser.parse(xml)

        assert result is None

    def test_parse_with_multiple_tags_finds_supported(self):
        """Test that parser finds supported tag among multiple tags."""
        parser = XMLToolParser()
        xml = """
        <unsupported>content</unsupported>
        <read_file>src/main.py</read_file>
        <another_unsupported>more content</another_unsupported>
        """

        result = parser.parse(xml)

        assert result is not None
        assert result.canonical_name == "read_file"
