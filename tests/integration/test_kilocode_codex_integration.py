"""Integration tests for KiloCode-Codex compatibility."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from src.connectors.openai_codex import OpenAICodexConnector
from src.connectors._openai_codex_capabilities import CodexCapabilityResolver
from src.core.commands.tool_call_text_parser import parse_textual_tool_invocation
from src.core.config.app_config import AppConfig
from src.core.services.translation_service import TranslationService


class TestKiloCodeCodexIntegration:
    """Integration tests for KiloCode compatibility with Codex connector."""

    @pytest_asyncio.fixture
    async def temp_workspace(self):
        """Create a temporary workspace for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            
            # Create test files
            (workspace / "README.md").write_text("# Test Project\n\nThis is a test project.")
            (workspace / "src").mkdir()
            (workspace / "src" / "main.py").write_text("def main():\n    print('Hello, World!')")
            (workspace / "tests").mkdir()
            (workspace / "tests" / "test_main.py").write_text("import unittest\n\nclass TestMain(unittest.TestCase):\n    pass")
            
            yield workspace

    @pytest_asyncio.fixture
    async def codex_connector(self, temp_workspace):
        """Create a Codex connector for testing."""
        import httpx
        
        async with httpx.AsyncClient() as client:
            cfg = AppConfig()
            ts = TranslationService()
            connector = OpenAICodexConnector(client, cfg, translation_service=ts)
            
            # Mock the credential validation for testing
            with (
                patch.object(connector, "_validate_credentials_file_exists", return_value=(True, [])),
                patch.object(connector, "_validate_credentials_structure", return_value=(True, [])),
                patch.object(connector, "_start_file_watching"),
                patch.object(connector, "api_key", "test_key"),
            ):
                # Initialize the KiloCode executor with the test workspace
                connector._kilocode_executor = None  # Reset to test lazy initialization
                
                # Change working directory for the executor
                import os
                original_cwd = os.getcwd()
                os.chdir(str(temp_workspace))
                try:
                    yield connector
                finally:
                    os.chdir(original_cwd)

    def test_kilocode_agent_detection(self):
        """Test that KiloCode agents are properly detected."""
        resolver = CodexCapabilityResolver()
        
        test_cases = [
            "kilocode",
            "KiloCode", 
            "kilo-code",
            "kilocode/1.0",
            "KiloCode.ai"
        ]
        
        for agent_name in test_cases:
            metadata = {"agent": agent_name}
            request_data = type('MockRequest', (), {})()
            
            capabilities = resolver.resolve(request_data, metadata)
            assert capabilities.tool_text_format == "codex_xml", f"Failed for agent: {agent_name}"

    def test_kilocode_xml_parsing_read_file(self):
        """Test parsing of KiloCode read_file XML."""
        xml_variants = [
            '<read_file file_path="README.md"></read_file>',
            '<read_file path="src/main.py">src/main.py</read_file>',
            '<read_file>tests/test_main.py</read_file>'
        ]
        
        for xml in xml_variants:
            result = parse_textual_tool_invocation(xml)
            assert result is not None, f"Failed to parse: {xml}"
            assert result.canonical_name == "read_file"
            assert "file_path" in result.arguments

    def test_kilocode_xml_parsing_list_files(self):
        """Test parsing of KiloCode list_files XML."""
        xml_variants = [
            '<list_files path="src" recursive="true"></list_files>',
            '<list_files></list_files>',
            '<list_files path=".">.</list_files>'
        ]
        
        for xml in xml_variants:
            result = parse_textual_tool_invocation(xml)
            assert result is not None, f"Failed to parse: {xml}"
            assert result.canonical_name == "list_dir"
            assert "dir_path" in result.arguments

    def test_kilocode_xml_parsing_search_files(self):
        """Test parsing of KiloCode search XML."""
        xml_variants = [
            '<codebase_search pattern="def main"></codebase_search>',
            '<search_files>import unittest</search_files>',
            '<codebase_search pattern="print" path="src"></codebase_search>'
        ]
        
        for xml in xml_variants:
            result = parse_textual_tool_invocation(xml)
            assert result is not None, f"Failed to parse: {xml}"
            assert result.canonical_name == "grep_files"
            assert "pattern" in result.arguments

    def test_kilocode_xml_parsing_completion_markers(self):
        """Test parsing of KiloCode completion markers."""
        xml_variants = [
            '<attempt_completion>Task completed successfully</attempt_completion>',
            '<ask_followup_question>Do you need help with anything else?</ask_followup_question>'
        ]
        
        expected_names = ["completion_marker", "followup_marker"]
        
        for xml, expected_name in zip(xml_variants, expected_names):
            result = parse_textual_tool_invocation(xml)
            assert result is not None, f"Failed to parse: {xml}"
            assert result.canonical_name == expected_name

    async def test_kilocode_tool_schema_generation(self, codex_connector):
        """Test that KiloCode tools are included in the tool schema."""
        tools = codex_connector._default_codex_tools()
        
        # Check that base Codex tools are present
        tool_names = {tool["name"] for tool in tools}
        assert "shell" in tool_names
        assert "apply_patch" in tool_names
        assert "view_image" in tool_names
        
        # Check that KiloCode tools are present
        kilocode_tools = {
            "read_file", "list_dir", "grep_files", 
            "use_mcp_tool", "completion_marker", "followup_marker"
        }
        for tool_name in kilocode_tools:
            assert tool_name in tool_names, f"Missing KiloCode tool: {tool_name}"

    async def test_kilocode_tool_execution_read_file(self, codex_connector):
        """Test execution of KiloCode read_file tool."""
        result = await codex_connector._execute_kilocode_tool("read_file", {
            "file_path": "README.md"
        })
        
        assert result["exit_code"] == 0
        assert "Test Project" in result["output"]
        assert "workdir" in result

    async def test_kilocode_tool_execution_list_dir(self, codex_connector):
        """Test execution of KiloCode list_dir tool."""
        result = await codex_connector._execute_kilocode_tool("list_dir", {
            "dir_path": "."
        })
        
        assert result["exit_code"] == 0
        assert "README.md" in result["output"]
        assert "src" in result["output"]
        assert "tests" in result["output"]

    async def test_kilocode_tool_execution_grep_files(self, codex_connector):
        """Test execution of KiloCode grep_files tool."""
        result = await codex_connector._execute_kilocode_tool("grep_files", {
            "pattern": "def main",
            "path": "."
        })
        
        assert result["exit_code"] == 0
        assert "main.py" in result["output"]

    async def test_kilocode_tool_execution_completion_marker(self, codex_connector):
        """Test execution of KiloCode completion marker."""
        result = await codex_connector._execute_kilocode_tool("completion_marker", {
            "result": "Successfully created the test project"
        })
        
        assert result["exit_code"] == 0
        assert "[COMPLETION]" in result["output"]
        assert "Successfully created the test project" in result["output"]

    async def test_kilocode_tool_execution_followup_marker(self, codex_connector):
        """Test execution of KiloCode followup marker."""
        result = await codex_connector._execute_kilocode_tool("followup_marker", {
            "question": "Would you like me to add more tests?"
        })
        
        assert result["exit_code"] == 0
        assert "[FOLLOWUP]" in result["output"]
        assert "Would you like me to add more tests?" in result["output"]

    async def test_kilocode_tool_execution_error_handling(self, codex_connector):
        """Test error handling in KiloCode tool execution."""
        # Test reading non-existent file
        result = await codex_connector._execute_kilocode_tool("read_file", {
            "file_path": "nonexistent.txt"
        })
        
        assert result["exit_code"] == 1
        assert "not found" in result["output"].lower()

    async def test_kilocode_executor_lazy_initialization(self, codex_connector):
        """Test that KiloCode executor is lazily initialized."""
        # Executor should be None initially
        assert codex_connector._kilocode_executor is None
        
        # First call should initialize it
        executor1 = codex_connector._get_kilocode_executor()
        assert executor1 is not None
        assert codex_connector._kilocode_executor is executor1
        
        # Second call should return the same instance
        executor2 = codex_connector._get_kilocode_executor()
        assert executor2 is executor1

    def test_kilocode_tool_schema_validation(self, codex_connector):
        """Test that KiloCode tool schemas are valid."""
        kilocode_tools = codex_connector._get_kilocode_tools()
        
        for tool in kilocode_tools:
            # Check required fields
            assert "type" in tool
            assert "name" in tool
            assert "description" in tool
            assert "parameters" in tool
            
            # Check parameter structure
            params = tool["parameters"]
            assert "type" in params
            assert params["type"] == "object"
            assert "properties" in params
            assert "required" in params
            
            # Check that required parameters are actually in properties
            for required_param in params["required"]:
                assert required_param in params["properties"]

    async def test_end_to_end_kilocode_workflow(self, codex_connector):
        """Test a complete KiloCode workflow."""
        # 1. List files in the project
        list_result = await codex_connector._execute_kilocode_tool("list_dir", {
            "dir_path": ".",
            "recursive": True
        })
        assert list_result["exit_code"] == 0
        assert "main.py" in list_result["output"]
        
        # 2. Read the main file
        read_result = await codex_connector._execute_kilocode_tool("read_file", {
            "file_path": "src/main.py"
        })
        assert read_result["exit_code"] == 0
        assert "def main" in read_result["output"]
        
        # 3. Search for function definitions
        search_result = await codex_connector._execute_kilocode_tool("grep_files", {
            "pattern": "def ",
            "path": "src"
        })
        assert search_result["exit_code"] == 0
        assert "main.py" in search_result["output"]
        
        # 4. Mark completion
        completion_result = await codex_connector._execute_kilocode_tool("completion_marker", {
            "result": "Project analysis completed"
        })
        assert completion_result["exit_code"] == 0
        assert "[COMPLETION]" in completion_result["output"]