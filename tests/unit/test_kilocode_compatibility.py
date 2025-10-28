"""Unit tests for KiloCode compatibility features."""

from src.connectors._openai_codex_capabilities import CodexCapabilityResolver
from src.core.commands.tool_call_text_parser import parse_textual_tool_invocation


class TestKiloCodeDetection:
    """Test KiloCode agent detection logic."""

    def test_kilocode_detection_explicit_metadata(self):
        """Test detection via explicit metadata."""
        resolver = CodexCapabilityResolver()

        metadata = {"agent": "kilocode"}
        request_data = type("MockRequest", (), {})()

        capabilities = resolver.resolve(request_data, metadata)
        assert capabilities.tool_text_format == "codex_xml"

    def test_kilocode_detection_case_insensitive(self):
        """Test case-insensitive detection."""
        resolver = CodexCapabilityResolver()

        test_cases = [
            "KiloCode",
            "KILOCODE",
            "kilocode",
            "Kilo-Code",
            "kilo_code",
            "kilocode.ai",
        ]
        for agent_name in test_cases:
            metadata = {"agent": agent_name}
            request_data = type("MockRequest", (), {})()

            capabilities = resolver.resolve(request_data, metadata)
            assert (
                capabilities.tool_text_format == "codex_xml"
            ), f"Failed for agent: {agent_name}"

    def test_kilocode_detection_request_attribute(self):
        """Test detection via request.agent attribute."""
        resolver = CodexCapabilityResolver()

        request_data = type("MockRequest", (), {"agent": "kilocode"})()

        capabilities = resolver.resolve(request_data, None)
        assert capabilities.tool_text_format == "codex_xml"

    def test_kilocode_detection_with_version(self):
        """Test detection with version suffixes."""
        resolver = CodexCapabilityResolver()

        test_cases = ["kilocode/1.0", "KiloCode/2.5.1", "kilo-code/beta"]
        for agent_name in test_cases:
            metadata = {"agent": agent_name}
            request_data = type("MockRequest", (), {})()

            capabilities = resolver.resolve(request_data, metadata)
            assert (
                capabilities.tool_text_format == "codex_xml"
            ), f"Failed for agent: {agent_name}"

    def test_non_kilocode_agents_unchanged(self):
        """Test that non-KiloCode agents are not affected."""
        resolver = CodexCapabilityResolver()

        test_cases = ["cursor", "vscode", "other-agent", "code-assistant"]
        for agent_name in test_cases:
            metadata = {"agent": agent_name}
            request_data = type("MockRequest", (), {})()

            capabilities = resolver.resolve(request_data, metadata)
            # Should not automatically set codex_xml for non-KiloCode agents
            assert (
                capabilities.tool_text_format != "codex_xml"
                or capabilities.tool_text_format == "none"
            )


class TestKiloCodeXMLParsing:
    """Test KiloCode XML tool parsing."""

    def test_read_file_parsing_with_attributes(self):
        """Test parsing <read_file> with file_path attribute."""
        xml = '<read_file file_path="src/main.py"></read_file>'
        result = parse_textual_tool_invocation(xml)

        assert result is not None
        assert result.canonical_name == "read_file"
        assert result.arguments["file_path"] == "src/main.py"
        assert result.raw_text == xml

    def test_read_file_parsing_with_content(self):
        """Test parsing <read_file> with content."""
        xml = "<read_file>config.yaml</read_file>"
        result = parse_textual_tool_invocation(xml)

        assert result is not None
        assert result.canonical_name == "read_file"
        assert result.arguments["file_path"] == "config.yaml"

    def test_list_files_parsing_with_recursive(self):
        """Test parsing <list_files> with recursive option."""
        xml = '<list_files path="src" recursive="true"></list_files>'
        result = parse_textual_tool_invocation(xml)

        assert result is not None
        assert result.canonical_name == "list_dir"
        assert result.arguments["dir_path"] == "src"
        assert result.arguments["recursive"] is True

    def test_list_files_parsing_default_directory(self):
        """Test parsing <list_files> with default directory."""
        xml = "<list_files></list_files>"
        result = parse_textual_tool_invocation(xml)

        assert result is not None
        assert result.canonical_name == "list_dir"
        assert result.arguments["dir_path"] == "."

    def test_codebase_search_parsing(self):
        """Test parsing <codebase_search> XML."""
        xml = '<codebase_search pattern="def main"></codebase_search>'
        result = parse_textual_tool_invocation(xml)

        assert result is not None
        assert result.canonical_name == "grep_files"
        assert result.arguments["pattern"] == "def main"

    def test_search_files_parsing(self):
        """Test parsing <search_files> XML."""
        xml = "<search_files>import os</search_files>"
        result = parse_textual_tool_invocation(xml)

        assert result is not None
        assert result.canonical_name == "grep_files"
        assert result.arguments["pattern"] == "import os"

    def test_use_mcp_tool_patch_file(self):
        """Test parsing <use_mcp_tool> for patch_file operations."""
        xml = """<use_mcp_tool tool_name="patch_file" path="src/main.py">
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,4 @@
+# New comment
 def main():
     pass
</use_mcp_tool>"""
        result = parse_textual_tool_invocation(xml)

        assert result is not None
        assert result.canonical_name == "use_mcp_tool"
        assert result.arguments["tool_name"] == "patch_file"
        assert result.arguments["path"] == "src/main.py"
        assert "# New comment" in result.arguments["arguments"]
        assert "patch_content" in result.arguments  # Special handling for patch_file

    def test_use_mcp_tool_generic(self):
        """Test parsing <use_mcp_tool> for generic MCP tools."""
        xml = '<use_mcp_tool tool_name="custom_tool">{"arg1": "value1"}</use_mcp_tool>'
        result = parse_textual_tool_invocation(xml)

        assert result is not None
        assert result.canonical_name == "use_mcp_tool"
        assert result.arguments["tool_name"] == "custom_tool"
        assert result.arguments["arguments"] == '{"arg1": "value1"}'

    def test_attempt_completion_parsing(self):
        """Test parsing <attempt_completion> XML."""
        xml = "<attempt_completion>Task completed successfully</attempt_completion>"
        result = parse_textual_tool_invocation(xml)

        assert result is not None
        assert result.canonical_name == "completion_marker"
        assert result.arguments["result"] == "Task completed successfully"

    def test_ask_followup_question_parsing(self):
        """Test parsing <ask_followup_question> XML."""
        xml = "<ask_followup_question>Do you want me to add tests?</ask_followup_question>"
        result = parse_textual_tool_invocation(xml)

        assert result is not None
        assert result.canonical_name == "followup_marker"
        assert result.arguments["question"] == "Do you want me to add tests?"

    def test_legacy_tools_still_work(self):
        """Test that legacy Cline/Codex tools still work."""
        # Test execute_command
        xml1 = "<execute_command><command>ls -la</command></execute_command>"
        result1 = parse_textual_tool_invocation(xml1)
        assert result1 is not None
        assert result1.canonical_name == "shell"

        # Test apply_diff
        xml2 = "<apply_diff><path>test.py</path><diff>--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new</diff></apply_diff>"
        result2 = parse_textual_tool_invocation(xml2)
        assert result2 is not None
        assert result2.canonical_name == "apply_patch"

    def test_invalid_xml_returns_none(self):
        """Test that invalid XML returns None."""
        invalid_cases = [
            "",
            "<invalid_tool>content</invalid_tool>",
            "<read_file></read_file>",  # No path
            "<use_mcp_tool>no tool name</use_mcp_tool>",  # No tool_name attribute
        ]

        for xml in invalid_cases:
            result = parse_textual_tool_invocation(xml)
            assert result is None, f"Expected None for: {xml}"
