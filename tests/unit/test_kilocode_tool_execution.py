"""Unit tests for KiloCode tool execution."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest_asyncio
from src.core.services.kilocode_tool_executor import KiloCodeToolExecutor


class TestKiloCodeToolExecutor:
    """Test KiloCode tool execution functionality."""

    @pytest_asyncio.fixture
    async def temp_workspace(self):
        """Create a temporary workspace for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)

            # Create test files and directories
            (workspace / "test_file.txt").write_text("Hello, World!\nLine 2\nLine 3")
            (workspace / "test_dir").mkdir()
            (workspace / "test_dir" / "nested_file.py").write_text(
                "def hello():\n    print('Hello')"
            )
            (workspace / ".hidden_file").write_text("Hidden content")

            yield workspace

    @pytest_asyncio.fixture
    async def executor(self, temp_workspace):
        """Create a KiloCode tool executor."""
        return KiloCodeToolExecutor(working_directory=str(temp_workspace))

    async def test_read_file_success(self, executor, temp_workspace):
        """Test successful file reading."""
        result = await executor.execute_tool(
            "read_file", {"file_path": "test_file.txt"}
        )

        assert result["exit_code"] == 0
        assert "Hello, World!" in result["output"]
        assert "Line 2" in result["output"]
        assert "Line 3" in result["output"]
        assert "file_path" in result

    async def test_read_file_with_line_range(self, executor, temp_workspace):
        """Test file reading with line range."""
        result = await executor.execute_tool(
            "read_file", {"file_path": "test_file.txt", "start_line": 2, "end_line": 3}
        )

        assert result["exit_code"] == 0
        assert result["output"] == "Line 2\nLine 3"

    async def test_read_file_not_found(self, executor, temp_workspace):
        """Test reading non-existent file."""
        result = await executor.execute_tool(
            "read_file", {"file_path": "nonexistent.txt"}
        )

        assert result["exit_code"] == 1
        assert "not found" in result["output"].lower()
        assert "error" in result

    async def test_read_file_missing_path(self, executor, temp_workspace):
        """Test reading file without path parameter."""
        result = await executor.execute_tool("read_file", {})

        assert result["exit_code"] == 1
        assert "file_path is required" in result["output"]

    async def test_list_dir_success(self, executor, temp_workspace):
        """Test successful directory listing."""
        result = await executor.execute_tool("list_dir", {"dir_path": "."})

        assert result["exit_code"] == 0
        assert "test_file.txt" in result["output"]
        assert "test_dir" in result["output"]
        assert "count" in result

    async def test_list_dir_recursive(self, executor, temp_workspace):
        """Test recursive directory listing."""
        result = await executor.execute_tool(
            "list_dir", {"dir_path": ".", "recursive": True}
        )

        assert result["exit_code"] == 0
        assert "test_file.txt" in result["output"]
        assert "nested_file.py" in result["output"]

    async def test_list_dir_include_hidden(self, executor, temp_workspace):
        """Test directory listing with hidden files."""
        result = await executor.execute_tool(
            "list_dir", {"dir_path": ".", "include_hidden": True}
        )

        assert result["exit_code"] == 0
        assert ".hidden_file" in result["output"]

    async def test_list_dir_not_found(self, executor, temp_workspace):
        """Test listing non-existent directory."""
        result = await executor.execute_tool("list_dir", {"dir_path": "nonexistent"})

        assert result["exit_code"] == 1
        assert "not found" in result["output"].lower()

    async def test_grep_files_success(self, executor, temp_workspace):
        """Test successful file search."""
        result = await executor.execute_tool(
            "grep_files", {"pattern": "Hello", "path": "."}
        )

        assert result["exit_code"] == 0
        assert (
            "test_file.txt" in result["output"] or "nested_file.py" in result["output"]
        )
        assert "matches_count" in result

    async def test_grep_files_no_matches(self, executor, temp_workspace):
        """Test file search with no matches."""
        result = await executor.execute_tool(
            "grep_files", {"pattern": "NonexistentPattern", "path": "."}
        )

        assert result["exit_code"] == 0
        assert "No matches found" in result["output"]
        assert result["matches_count"] == 0

    async def test_grep_files_invalid_regex(self, executor, temp_workspace):
        """Test file search with invalid regex."""
        result = await executor.execute_tool(
            "grep_files", {"pattern": "[invalid", "path": "."}
        )

        assert result["exit_code"] == 1
        assert "Invalid regex" in result["output"]

    async def test_grep_files_missing_pattern(self, executor, temp_workspace):
        """Test file search without pattern."""
        result = await executor.execute_tool("grep_files", {"path": "."})

        assert result["exit_code"] == 1
        assert "pattern is required" in result["output"]

    async def test_use_mcp_tool_placeholder(self, executor, temp_workspace):
        """Test MCP tool placeholder implementation."""
        result = await executor.execute_tool(
            "use_mcp_tool", {"tool_name": "test_tool", "arguments": '{"key": "value"}'}
        )

        assert result["exit_code"] == 0
        assert "test_tool" in result["output"]
        assert "note" in result
        assert "not yet implemented" in result["note"].lower()

    async def test_completion_marker(self, executor, temp_workspace):
        """Test completion marker tool."""
        result = await executor.execute_tool(
            "completion_marker", {"result": "Task completed successfully"}
        )

        assert result["exit_code"] == 0
        assert "[COMPLETION]" in result["output"]
        assert "Task completed successfully" in result["output"]
        assert result["marker_type"] == "completion"

    async def test_followup_marker(self, executor, temp_workspace):
        """Test followup marker tool."""
        result = await executor.execute_tool(
            "followup_marker", {"question": "Do you need help with anything else?"}
        )

        assert result["exit_code"] == 0
        assert "[FOLLOWUP]" in result["output"]
        assert "Do you need help with anything else?" in result["output"]
        assert result["marker_type"] == "followup"

    async def test_unknown_tool(self, executor, temp_workspace):
        """Test execution of unknown tool."""
        result = await executor.execute_tool("unknown_tool", {})

        assert result["exit_code"] == 1
        assert "Unknown KiloCode tool" in result["output"]

    async def test_tool_execution_exception(self, executor, temp_workspace):
        """Test tool execution with exception."""
        # Mock the _execute_read_file method to raise an exception
        with patch.object(
            executor, "_execute_read_file", side_effect=Exception("Test error")
        ):
            result = await executor.execute_tool("read_file", {"file_path": "test.txt"})

            assert result["exit_code"] == 1
            assert "Error executing read_file" in result["output"]
            assert "Test error" in result["output"]


class TestKiloCodeToolExecutorIntegration:
    """Integration tests for KiloCode tool executor."""

    async def test_file_operations_workflow(self):
        """Test a complete workflow of file operations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            executor = KiloCodeToolExecutor(working_directory=temp_dir)
            workspace = Path(temp_dir)

            # Create a test file
            test_file = workspace / "workflow_test.py"
            test_file.write_text(
                "def main():\n    print('Hello, World!')\n\nif __name__ == '__main__':\n    main()"
            )

            # Test reading the file
            read_result = await executor.execute_tool(
                "read_file", {"file_path": "workflow_test.py"}
            )
            assert read_result["exit_code"] == 0
            assert "def main():" in read_result["output"]

            # Test listing the directory
            list_result = await executor.execute_tool("list_dir", {"dir_path": "."})
            assert list_result["exit_code"] == 0
            assert "workflow_test.py" in list_result["output"]

            # Test searching for content
            grep_result = await executor.execute_tool(
                "grep_files", {"pattern": "def main", "path": "."}
            )
            assert grep_result["exit_code"] == 0
            assert "workflow_test.py" in grep_result["output"]

    async def test_error_handling_workflow(self):
        """Test error handling in various scenarios."""
        with tempfile.TemporaryDirectory() as temp_dir:
            executor = KiloCodeToolExecutor(working_directory=temp_dir)

            # Test reading non-existent file
            result = await executor.execute_tool(
                "read_file", {"file_path": "missing.txt"}
            )
            assert result["exit_code"] == 1

            # Test listing non-existent directory
            result = await executor.execute_tool(
                "list_dir", {"dir_path": "missing_dir"}
            )
            assert result["exit_code"] == 1

            # Test searching in non-existent path
            result = await executor.execute_tool(
                "grep_files", {"pattern": "test", "path": "missing_path"}
            )
            assert result["exit_code"] == 1
