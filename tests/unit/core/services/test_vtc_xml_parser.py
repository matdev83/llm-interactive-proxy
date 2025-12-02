"""Unit tests for VTC XML parser module."""

import json

from src.core.services.vtc_xml_parser import (
    detect_complete_tool_call,
    has_partial_xml_pattern,
    parse_vtc_xml,
    serialize_tool_calls_to_xml,
)


class TestParseVtcXml:
    """Tests for the parse_vtc_xml function."""

    def test_parse_empty_content(self) -> None:
        """Test parsing empty content."""
        tool_calls, cleaned = parse_vtc_xml("")
        assert tool_calls == []
        assert cleaned == ""

    def test_parse_none_content(self) -> None:
        """Test parsing None-like content (empty string)."""
        tool_calls, cleaned = parse_vtc_xml("")
        assert tool_calls == []
        assert cleaned == ""

    def test_parse_content_without_tool_calls(self) -> None:
        """Test parsing content without any tool calls."""
        content = "This is regular text without any tool calls."
        tool_calls, cleaned = parse_vtc_xml(content)
        assert tool_calls == []
        assert cleaned == content

    def test_parse_invoke_format_single_param(self) -> None:
        """Test parsing invoke format with single parameter."""
        content = """<function_calls>
<invoke name="execute_command">
<parameter name="command">ls -la</parameter>
</invoke>
</function_calls>"""

        tool_calls, cleaned = parse_vtc_xml(content)

        assert len(tool_calls) == 1
        assert tool_calls[0]["type"] == "function"
        assert tool_calls[0]["function"]["name"] == "execute_command"

        args = json.loads(tool_calls[0]["function"]["arguments"])
        assert args["command"] == "ls -la"
        assert cleaned == ""

    def test_parse_invoke_format_multiple_params(self) -> None:
        """Test parsing invoke format with multiple parameters."""
        content = """<function_calls>
<invoke name="write_file">
<parameter name="path">/tmp/test.txt</parameter>
<parameter name="content">Hello World</parameter>
</invoke>
</function_calls>"""

        tool_calls, cleaned = parse_vtc_xml(content)

        assert len(tool_calls) == 1
        args = json.loads(tool_calls[0]["function"]["arguments"])
        assert args["path"] == "/tmp/test.txt"
        assert args["content"] == "Hello World"

    def test_parse_invoke_format_with_namespace_prefix(self) -> None:
        """Test parsing invoke format with namespace prefix in name."""
        content = """<invoke name="antml:tool:read_file">
<parameter name="path">/tmp/test.txt</parameter>
</invoke>"""

        tool_calls, cleaned = parse_vtc_xml(content)

        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "read_file"

    def test_parse_invoke_format_with_client_controls_prefix(self) -> None:
        """Test parsing invoke format with ClientControls namespace prefix."""
        content = """<invoke name="ClientControls:run_terminal_command">
<parameter name="command">echo hello</parameter>
</invoke>"""

        tool_calls, cleaned = parse_vtc_xml(content)

        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "run_terminal_command"

    def test_parse_multiple_invoke_calls(self) -> None:
        """Test parsing multiple invoke calls."""
        content = """<function_calls>
<invoke name="tool_a">
<parameter name="arg">value_a</parameter>
</invoke>
<invoke name="tool_b">
<parameter name="arg">value_b</parameter>
</invoke>
</function_calls>"""

        tool_calls, cleaned = parse_vtc_xml(content)

        assert len(tool_calls) == 2
        assert tool_calls[0]["function"]["name"] == "tool_a"
        assert tool_calls[1]["function"]["name"] == "tool_b"

    def test_parse_mixed_content_and_tool_calls(self) -> None:
        """Test parsing content that has both text and tool calls."""
        content = """I will execute the command now.
<function_calls>
<invoke name="execute_command">
<parameter name="command">ls</parameter>
</invoke>
</function_calls>
Here is the output."""

        tool_calls, cleaned = parse_vtc_xml(content)

        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "execute_command"
        assert "I will execute the command now." in cleaned
        assert "Here is the output." in cleaned
        assert "<invoke" not in cleaned

    def test_parse_with_allowed_tools_whitelist(self) -> None:
        """Test that allowed_tools whitelist filters tool calls."""
        content = """<invoke name="allowed_tool">
<parameter name="arg">value</parameter>
</invoke>
<invoke name="blocked_tool">
<parameter name="arg">value</parameter>
</invoke>"""

        tool_calls, cleaned = parse_vtc_xml(content, allowed_tools=["allowed_tool"])

        assert len(tool_calls) == 1
        assert tool_calls[0]["function"]["name"] == "allowed_tool"
        # blocked_tool XML should still be in content since it wasn't extracted
        assert "blocked_tool" in cleaned

    def test_parse_json_parameter_value(self) -> None:
        """Test parsing parameter with JSON value."""
        content = """<invoke name="todo_write">
<parameter name="todos">[{"id": "1", "content": "Task 1"}]</parameter>
</invoke>"""

        tool_calls, cleaned = parse_vtc_xml(content)

        assert len(tool_calls) == 1
        args = json.loads(tool_calls[0]["function"]["arguments"])
        assert isinstance(args["todos"], list)
        assert args["todos"][0]["id"] == "1"

    def test_parse_integer_parameter_value(self) -> None:
        """Test parsing parameter with integer value."""
        content = """<invoke name="test_tool">
<parameter name="count">42</parameter>
</invoke>"""

        tool_calls, cleaned = parse_vtc_xml(content)

        args = json.loads(tool_calls[0]["function"]["arguments"])
        assert args["count"] == 42

    def test_parse_boolean_parameter_values(self) -> None:
        """Test parsing parameter with boolean values."""
        content = """<invoke name="test_tool">
<parameter name="enabled">true</parameter>
<parameter name="disabled">false</parameter>
</invoke>"""

        tool_calls, cleaned = parse_vtc_xml(content)

        args = json.loads(tool_calls[0]["function"]["arguments"])
        assert args["enabled"] is True
        assert args["disabled"] is False

    def test_parse_tool_call_id_format(self) -> None:
        """Test that generated tool call IDs have expected format."""
        content = """<invoke name="test">
<parameter name="x">1</parameter>
</invoke>"""

        tool_calls, _ = parse_vtc_xml(content)

        assert len(tool_calls) == 1
        assert tool_calls[0]["id"].startswith("vtc_")
        assert len(tool_calls[0]["id"]) == 16  # vtc_ + 12 hex chars


class TestSerializeToolCallsToXml:
    """Tests for the serialize_tool_calls_to_xml function."""

    def test_serialize_empty_list(self) -> None:
        """Test serializing empty tool calls list."""
        result = serialize_tool_calls_to_xml([])
        assert result == ""

    def test_serialize_single_tool_call(self) -> None:
        """Test serializing a single tool call."""
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "execute_command",
                    "arguments": json.dumps({"command": "ls -la"}),
                },
            }
        ]

        result = serialize_tool_calls_to_xml(tool_calls)

        assert "<function_calls>" in result
        assert "</function_calls>" in result
        assert '<invoke name="execute_command">' in result
        assert '<parameter name="command">ls -la</parameter>' in result
        assert "</invoke>" in result

    def test_serialize_multiple_tool_calls(self) -> None:
        """Test serializing multiple tool calls."""
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "tool_a",
                    "arguments": json.dumps({"arg": "a"}),
                },
            },
            {
                "id": "call_2",
                "type": "function",
                "function": {
                    "name": "tool_b",
                    "arguments": json.dumps({"arg": "b"}),
                },
            },
        ]

        result = serialize_tool_calls_to_xml(tool_calls)

        assert result.count("<invoke") == 2
        assert result.count("</invoke>") == 2
        assert '<invoke name="tool_a">' in result
        assert '<invoke name="tool_b">' in result

    def test_serialize_escapes_xml_entities(self) -> None:
        """Test that XML entities are properly escaped."""
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "test",
                    "arguments": json.dumps({"text": "<script>alert('xss')</script>"}),
                },
            }
        ]

        result = serialize_tool_calls_to_xml(tool_calls)

        assert "&lt;script&gt;" in result
        assert "&apos;xss&apos;" in result
        assert "&lt;/script&gt;" in result

    def test_serialize_handles_boolean_params(self) -> None:
        """Test serializing boolean parameter values."""
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "test",
                    "arguments": json.dumps({"flag": True}),
                },
            }
        ]

        result = serialize_tool_calls_to_xml(tool_calls)

        assert '<parameter name="flag">true</parameter>' in result

    def test_serialize_handles_json_params(self) -> None:
        """Test serializing JSON object parameter values."""
        tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "test",
                    "arguments": json.dumps({"data": {"nested": "value"}}),
                },
            }
        ]

        result = serialize_tool_calls_to_xml(tool_calls)

        # JSON should be serialized as string with XML entities escaped
        # Quotes become &quot;
        assert "&quot;nested&quot;" in result
        assert "&quot;value&quot;" in result


class TestHasPartialXmlPattern:
    """Tests for the has_partial_xml_pattern function."""

    def test_empty_text(self) -> None:
        """Test with empty text."""
        assert has_partial_xml_pattern("") is False

    def test_no_xml(self) -> None:
        """Test with no XML content."""
        assert has_partial_xml_pattern("Just regular text") is False

    def test_unclosed_tag(self) -> None:
        """Test with unclosed tag."""
        assert has_partial_xml_pattern("Some text <function") is True

    def test_unclosed_invoke(self) -> None:
        """Test with unclosed invoke tag."""
        assert has_partial_xml_pattern("<invoke name=") is True

    def test_opening_function_calls_without_close(self) -> None:
        """Test with opening function_calls but no closing."""
        assert has_partial_xml_pattern("<function_calls>\n<invoke") is True

    def test_complete_invoke(self) -> None:
        """Test with complete invoke (should be False)."""
        text = '<invoke name="test"></invoke>'
        assert has_partial_xml_pattern(text) is False


class TestDetectCompleteToolCall:
    """Tests for the detect_complete_tool_call function."""

    def test_empty_text(self) -> None:
        """Test with empty text."""
        assert detect_complete_tool_call("") is False

    def test_no_tool_call(self) -> None:
        """Test with no tool call."""
        assert detect_complete_tool_call("Regular text") is False

    def test_complete_invoke(self) -> None:
        """Test with complete invoke pattern."""
        text = '<invoke name="test"><parameter name="x">1</parameter></invoke>'
        assert detect_complete_tool_call(text) is True

    def test_complete_function_calls(self) -> None:
        """Test with complete function_calls block."""
        text = '<function_calls><invoke name="t"></invoke></function_calls>'
        assert detect_complete_tool_call(text) is True

    def test_partial_invoke(self) -> None:
        """Test with partial invoke (should be False)."""
        text = '<invoke name="test">'
        assert detect_complete_tool_call(text) is False


class TestRoundTrip:
    """Test round-trip parsing and serialization."""

    def test_round_trip_single_tool_call(self) -> None:
        """Test that parse -> serialize produces equivalent output."""
        original = """<function_calls>
<invoke name="execute_command">
<parameter name="command">ls -la</parameter>
</invoke>
</function_calls>"""

        tool_calls, _ = parse_vtc_xml(original)
        serialized = serialize_tool_calls_to_xml(tool_calls)

        # Re-parse the serialized version
        reparsed, _ = parse_vtc_xml(serialized)

        assert len(reparsed) == len(tool_calls)
        assert reparsed[0]["function"]["name"] == tool_calls[0]["function"]["name"]

        orig_args = json.loads(tool_calls[0]["function"]["arguments"])
        new_args = json.loads(reparsed[0]["function"]["arguments"])
        assert orig_args == new_args

    def test_round_trip_multiple_params(self) -> None:
        """Test round-trip with multiple parameters."""
        original = """<invoke name="write_file">
<parameter name="path">/tmp/file.txt</parameter>
<parameter name="content">Hello World</parameter>
<parameter name="overwrite">true</parameter>
</invoke>"""

        tool_calls, _ = parse_vtc_xml(original)
        serialized = serialize_tool_calls_to_xml(tool_calls)
        reparsed, _ = parse_vtc_xml(serialized)

        orig_args = json.loads(tool_calls[0]["function"]["arguments"])
        new_args = json.loads(reparsed[0]["function"]["arguments"])

        assert orig_args["path"] == new_args["path"]
        assert orig_args["content"] == new_args["content"]
        assert orig_args["overwrite"] == new_args["overwrite"]
