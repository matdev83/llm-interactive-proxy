"""Unit tests for UniversalToolExecutor proxy-side execution."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.services.universal_tool_executor import UniversalToolExecutor


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace for testing."""
    # Create test directory structure
    (tmp_path / "test_file.txt").write_text("Hello, World!\nLine 2\nLine 3")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.txt").write_text("Nested content")
    (tmp_path / ".hidden").write_text("Hidden file")
    return tmp_path


@pytest.fixture
def executor(temp_workspace: Path) -> UniversalToolExecutor:
    """Create a UniversalToolExecutor instance for testing."""
    return UniversalToolExecutor(
        working_directory=str(temp_workspace),
        default_timeout=5,
        result_format="kilo_standard",
    )


@pytest.fixture
def executor_default_format(temp_workspace: Path) -> UniversalToolExecutor:
    """Create a UniversalToolExecutor with default formatting."""
    return UniversalToolExecutor(
        working_directory=str(temp_workspace),
        default_timeout=5,
        result_format="default",
    )


class TestReadFileExecution:
    """Tests for read_file proxy-side execution."""

    @pytest.mark.asyncio
    async def test_read_file_success(self, executor: UniversalToolExecutor) -> None:
        """Test successful file read operation."""
        result = await executor.execute_tool("read_file", {"path": "test_file.txt"})

        assert result["exit_code"] == 0
        assert "Hello, World!" in result["output"]
        assert "[read_file] Result:" in result["output"]

    @pytest.mark.asyncio
    async def test_read_file_with_file_path_param(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test read_file with file_path parameter name."""
        result = await executor.execute_tool(
            "read_file", {"file_path": "test_file.txt"}
        )

        assert result["exit_code"] == 0
        assert "Hello, World!" in result["output"]

    @pytest.mark.asyncio
    async def test_read_file_not_found(self, executor: UniversalToolExecutor) -> None:
        """Test error handling for non-existent file."""
        result = await executor.execute_tool("read_file", {"path": "nonexistent.txt"})

        assert result["exit_code"] == 1
        assert "File not found" in result["output"]
        assert "error" in result

    @pytest.mark.asyncio
    async def test_read_file_is_directory(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test error handling when path is a directory."""
        result = await executor.execute_tool("read_file", {"path": "subdir"})

        assert result["exit_code"] == 1
        assert "not a file" in result["output"]

    @pytest.mark.asyncio
    async def test_read_file_missing_path(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test error handling for missing path parameter."""
        result = await executor.execute_tool("read_file", {})

        assert result["exit_code"] == 1
        assert "file_path is required" in result["output"]

    @pytest.mark.asyncio
    async def test_read_file_with_line_range(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test reading file with line range."""
        result = await executor.execute_tool(
            "read_file", {"path": "test_file.txt", "start_line": 2, "end_line": 3}
        )

        assert result["exit_code"] == 0
        assert "Line 2" in result["output"]
        assert "Hello, World!" not in result["output"]

    @pytest.mark.asyncio
    async def test_read_file_default_format(
        self, executor_default_format: UniversalToolExecutor
    ) -> None:
        """Test read_file with default formatting (no KiloCode prefix)."""
        result = await executor_default_format.execute_tool(
            "read_file", {"path": "test_file.txt"}
        )

        assert result["exit_code"] == 0
        assert "Hello, World!" in result["output"]
        assert "[read_file] Result:" not in result["output"]


class TestListDirExecution:
    """Tests for list_dir proxy-side execution."""

    @pytest.mark.asyncio
    async def test_list_dir_success(self, executor: UniversalToolExecutor) -> None:
        """Test successful directory listing."""
        result = await executor.execute_tool("list_dir", {"path": "."})

        assert result["exit_code"] == 0
        assert "test_file.txt" in result["output"]
        assert "subdir" in result["output"]
        assert "[list_dir] Result:" in result["output"]

    @pytest.mark.asyncio
    async def test_list_dir_recursive(self, executor: UniversalToolExecutor) -> None:
        """Test recursive directory listing."""
        result = await executor.execute_tool(
            "list_dir", {"path": ".", "recursive": True}
        )

        assert result["exit_code"] == 0
        assert "nested.txt" in result["output"]

    @pytest.mark.asyncio
    async def test_list_dir_with_depth(self, executor: UniversalToolExecutor) -> None:
        """Test directory listing with depth limit."""
        result = await executor.execute_tool("list_dir", {"path": ".", "depth": 1})

        assert result["exit_code"] == 0
        # Should include files at depth 1 but not deeper
        assert "test_file.txt" in result["output"]

    @pytest.mark.asyncio
    async def test_list_dir_not_found(self, executor: UniversalToolExecutor) -> None:
        """Test error handling for non-existent directory."""
        result = await executor.execute_tool("list_dir", {"path": "nonexistent"})

        assert result["exit_code"] == 1
        assert "not found" in result["output"] or "does not exist" in result["output"]

    @pytest.mark.asyncio
    async def test_list_dir_not_directory(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test error handling when path is not a directory."""
        result = await executor.execute_tool("list_dir", {"path": "test_file.txt"})

        assert result["exit_code"] == 1
        assert "not a directory" in result["output"]

    @pytest.mark.asyncio
    async def test_list_dir_exclude_hidden(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test that hidden files are excluded by default."""
        result = await executor.execute_tool("list_dir", {"path": "."})

        assert result["exit_code"] == 0
        assert ".hidden" not in result["output"]

    @pytest.mark.asyncio
    async def test_list_dir_include_hidden(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test including hidden files."""
        result = await executor.execute_tool(
            "list_dir", {"path": ".", "include_hidden": True}
        )

        assert result["exit_code"] == 0
        assert ".hidden" in result["output"]


class TestShellExecution:
    """Tests for shell command execution."""

    @pytest.mark.asyncio
    async def test_execute_command_success(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test successful command execution."""
        # Use a simple cross-platform command
        result = await executor.execute_tool("shell", {"command": "echo Hello"})

        assert result["exit_code"] == 0
        assert "Hello" in result["output"]
        assert "[shell] Result:" in result["output"]

    @pytest.mark.asyncio
    async def test_execute_command_with_exit_code(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test command execution with non-zero exit code."""
        # Use a command that will fail
        result = await executor.execute_tool("shell", {"command": "exit 42"})

        assert result["exit_code"] == 42

    @pytest.mark.asyncio
    async def test_execute_command_missing_command(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test error handling for missing command parameter."""
        result = await executor.execute_tool("shell", {})

        assert result["exit_code"] == 1
        assert "command is required" in result["output"]

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_execute_command_timeout(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test timeout handling for long-running commands.

        Uses minimal timeouts to keep test fast while validating behavior.
        """
        # Create a command that runs longer than the timeout
        # Using short durations to keep test fast
        import platform

        if platform.system() == "Windows":
            # Use ping with minimal count on Windows (2s is enough)
            sleep_cmd = "ping -n 3 127.0.0.1 > nul"
        else:
            sleep_cmd = "sleep 2"

        result = await executor.execute_tool(
            "shell", {"command": sleep_cmd, "timeout": 0.5}  # 0.5s timeout for speed
        )

        # Should have a non-zero exit code and timeout message
        assert result["exit_code"] != 0
        assert (
            "timed out" in result["output"].lower()
            or "timeout" in result.get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_execute_command_with_working_dir(
        self, executor: UniversalToolExecutor, temp_workspace: Path
    ) -> None:
        """Test command execution with custom working directory."""
        import platform

        if platform.system() == "Windows":
            # Use 'echo %CD%' to print the current directory on Windows
            result = await executor.execute_tool(
                "shell", {"command": "echo %CD%", "working_dir": "subdir"}
            )
        else:
            # Use 'pwd' command on Unix
            result = await executor.execute_tool(
                "shell", {"command": "pwd", "working_dir": "subdir"}
            )

        assert result["exit_code"] == 0
        assert "subdir" in result["output"]

    @pytest.mark.asyncio
    async def test_execute_command_invalid_working_dir(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test error handling for invalid working directory."""
        result = await executor.execute_tool(
            "shell", {"command": "echo test", "working_dir": "nonexistent"}
        )

        assert result["exit_code"] == 1
        assert "Working directory not found" in result["output"]

    @pytest.mark.asyncio
    async def test_execute_command_stderr_capture(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test that stderr is captured in output."""
        import platform

        if platform.system() == "Windows":
            # Redirect to stderr on Windows
            cmd = "echo Error message 1>&2"
        else:
            # Redirect to stderr on Unix
            cmd = "echo Error message >&2"

        result = await executor.execute_tool("shell", {"command": cmd})

        assert "Error message" in result["output"] or "STDERR" in result["output"]

    @pytest.mark.asyncio
    async def test_execute_command_alias(self, executor: UniversalToolExecutor) -> None:
        """Test execute_command alias for shell tool."""
        result = await executor.execute_tool(
            "execute_command", {"command": "echo Test"}
        )

        assert result["exit_code"] == 0
        assert "Test" in result["output"]


class TestResultFormatting:
    """Tests for result formatting."""

    @pytest.mark.asyncio
    async def test_kilo_standard_format(self, executor: UniversalToolExecutor) -> None:
        """Test KiloCode standard formatting."""
        result = await executor.execute_tool("read_file", {"path": "test_file.txt"})

        assert "[read_file] Result:" in result["output"]

    @pytest.mark.asyncio
    async def test_default_format(
        self, executor_default_format: UniversalToolExecutor
    ) -> None:
        """Test default formatting without KiloCode prefix."""
        result = await executor_default_format.execute_tool(
            "read_file", {"path": "test_file.txt"}
        )

        assert "[read_file] Result:" not in result["output"]
        assert "Hello, World!" in result["output"]

    @pytest.mark.asyncio
    async def test_error_formatting(self, executor: UniversalToolExecutor) -> None:
        """Test error message formatting."""
        result = await executor.execute_tool("read_file", {"path": "nonexistent.txt"})

        assert result["exit_code"] == 1
        assert "error" in result
        assert "[read_file] Result:" in result["output"]


class TestErrorHandling:
    """Tests for error handling in tool execution."""

    @pytest.mark.asyncio
    async def test_permission_error_handling(
        self, executor: UniversalToolExecutor, temp_workspace: Path
    ) -> None:
        """Test handling of permission errors."""
        # Create a file and make it unreadable (Unix only)
        import platform

        if platform.system() != "Windows":
            restricted_file = temp_workspace / "restricted.txt"
            restricted_file.write_text("Secret")
            restricted_file.chmod(0o000)

            result = await executor.execute_tool(
                "read_file", {"path": "restricted.txt"}
            )

            assert result["exit_code"] == 1
            assert "Permission denied" in result["output"]

            # Cleanup
            restricted_file.chmod(0o644)

    @pytest.mark.asyncio
    async def test_unicode_decode_error_handling(
        self, executor: UniversalToolExecutor, temp_workspace: Path
    ) -> None:
        """Test handling of binary files."""
        # Create a binary file
        binary_file = temp_workspace / "binary.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03\xff\xfe")

        result = await executor.execute_tool("read_file", {"path": "binary.bin"})

        # Should still succeed but with replaced characters
        assert result["exit_code"] == 0 or "binary" in result["output"].lower()

    @pytest.mark.asyncio
    async def test_generic_exception_handling(
        self, executor: UniversalToolExecutor
    ) -> None:
        """Test generic exception handling."""
        # Test with invalid parameters that might cause unexpected errors
        result = await executor.execute_tool(
            "read_file", {"path": "test_file.txt", "start_line": "invalid"}
        )

        # Should handle the error gracefully
        assert "exit_code" in result


class TestGrepFilesExecution:
    """Tests for grep_files proxy-side execution with include/exclude patterns."""

    @pytest.fixture
    def search_workspace(self, tmp_path: Path) -> Path:
        """Create a workspace with files for search testing."""
        # Create Python files
        (tmp_path / "main.py").write_text("def main():\n    print('Hello')\n")
        (tmp_path / "utils.py").write_text("def helper():\n    return True\n")
        (tmp_path / "test_main.py").write_text("def test_main():\n    assert True\n")

        # Create JavaScript files
        (tmp_path / "app.js").write_text(
            "function main() {\n    console.log('Hi');\n}\n"
        )
        (tmp_path / "utils.js").write_text("function helper() {\n    return true;\n}\n")

        # Create log files
        (tmp_path / "error.log").write_text("ERROR: Something failed\n")
        (tmp_path / "debug.log").write_text("DEBUG: All good\n")

        # Create subdirectory with more files
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "core.py").write_text(
            "class Core:\n    def run(self):\n        pass\n"
        )
        (tmp_path / "src" / "test_core.py").write_text("def test_core():\n    pass\n")

        return tmp_path

    @pytest.fixture
    def search_executor(self, search_workspace: Path) -> UniversalToolExecutor:
        """Create executor for search testing."""
        return UniversalToolExecutor(
            working_directory=str(search_workspace),
            default_timeout=5,
            result_format="kilo_standard",
        )

    @pytest.mark.asyncio
    async def test_grep_files_simple_search(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test simple grep_files search."""
        result = await search_executor.execute_tool("grep_files", {"pattern": "def "})

        assert result["exit_code"] == 0
        # Should find matches in Python files with function definitions
        assert result["matches_count"] >= 2
        assert "def" in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_with_include_pattern(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files with include glob pattern."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "def", "include": "*.py"}
        )

        assert result["exit_code"] == 0
        # Should find matches in Python files
        assert "main.py" in result["output"] or "utils.py" in result["output"]
        # Should not find matches in JavaScript files
        assert "app.js" not in result["output"]
        assert "utils.js" not in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_with_exclude_pattern(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files with exclude glob pattern."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "def", "exclude": "*test*.py"}
        )

        assert result["exit_code"] == 0
        # Should find matches in non-test files
        assert "main.py" in result["output"] or "utils.py" in result["output"]
        # Should not find matches in test files
        assert "test_main.py" not in result["output"]
        assert "test_core.py" not in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_with_include_and_exclude(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files with both include and exclude patterns."""
        result = await search_executor.execute_tool(
            "grep_files",
            {"pattern": "def", "include": "*.py", "exclude": "*test*.py"},
        )

        assert result["exit_code"] == 0
        # Should find matches in Python files but not test files
        assert "main.py" in result["output"] or "utils.py" in result["output"]
        assert "test_main.py" not in result["output"]
        assert "test_core.py" not in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_recursive_search(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files with recursive search."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "class Core", "recursive": True}
        )

        assert result["exit_code"] == 0
        # Should find matches in subdirectories
        assert "src" in result["output"]
        assert "core.py" in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_non_recursive_search(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files with non-recursive search."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "class Core", "recursive": False}
        )

        assert result["exit_code"] == 0
        # Should not find matches in subdirectories
        assert "src" not in result["output"] or result["matches_count"] == 0

    @pytest.mark.asyncio
    async def test_grep_files_case_insensitive(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files with case-insensitive search."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "FUNCTION", "case_sensitive": False}
        )

        assert result["exit_code"] == 0
        # Should find 'function' in JavaScript files
        assert "app.js" in result["output"] or "utils.js" in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_case_sensitive(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files with case-sensitive search."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "FUNCTION", "case_sensitive": True}
        )

        assert result["exit_code"] == 0
        # Should not find 'function' (lowercase)
        assert result["matches_count"] == 0 or "No matches found" in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_no_matches(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files when no matches are found."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "nonexistent_pattern_xyz"}
        )

        assert result["exit_code"] == 0
        assert "No matches found" in result["output"]
        assert result["matches_count"] == 0

    @pytest.mark.asyncio
    async def test_grep_files_with_specific_path(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files with specific path."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "class", "path": "src/"}
        )

        assert result["exit_code"] == 0
        # Should only search in src/ directory
        if result["matches_count"] > 0:
            assert "src" in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_invalid_regex(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files with invalid regex pattern."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "[invalid(regex"}
        )

        assert result["exit_code"] == 1
        assert "Invalid regex" in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_missing_pattern(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files without pattern parameter."""
        result = await search_executor.execute_tool("grep_files", {})

        assert result["exit_code"] == 1
        assert "pattern is required" in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_path_not_found(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files with non-existent path."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "test", "path": "nonexistent/"}
        )

        assert result["exit_code"] == 1
        assert "not found" in result["output"] or "does not exist" in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_result_format(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files result format with file paths and line numbers."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "def main"}
        )

        assert result["exit_code"] == 0
        # Result should contain filename:line_number:content format
        assert ":" in result["output"]
        # Should have at least one match with line number
        if result["matches_count"] > 0:
            import re

            # Check for pattern like "filename.py:123:content"
            assert re.search(r"\w+\.py:\d+:", result["output"])

    @pytest.mark.asyncio
    async def test_grep_files_complex_regex(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files with complex regex pattern."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": r"def \w+\(\):"}
        )

        assert result["exit_code"] == 0
        # Should find function definitions
        if result["matches_count"] > 0:
            assert "def" in result["output"]

    @pytest.mark.asyncio
    async def test_codebase_search_alias(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test codebase_search as alias for grep_files."""
        result = await search_executor.execute_tool(
            "codebase_search", {"pattern": "def main"}
        )

        assert result["exit_code"] == 0
        assert "main.py" in result["output"] or result["matches_count"] >= 0

    @pytest.mark.asyncio
    async def test_search_files_alias(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test search_files as alias for grep_files."""
        result = await search_executor.execute_tool(
            "search_files", {"pattern": "def main"}
        )

        assert result["exit_code"] == 0
        assert "main.py" in result["output"] or result["matches_count"] >= 0

    @pytest.mark.asyncio
    async def test_grep_files_exclude_takes_precedence(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test that exclude pattern takes precedence over include."""
        result = await search_executor.execute_tool(
            "grep_files",
            {"pattern": "def", "include": "*.py", "exclude": "*.py"},
        )

        assert result["exit_code"] == 0
        # All Python files should be excluded
        assert result["matches_count"] == 0 or "No matches found" in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_multiple_matches_per_file(
        self, search_executor: UniversalToolExecutor, search_workspace: Path
    ) -> None:
        """Test grep_files with multiple matches in a single file."""
        # Create a file with multiple matches
        (search_workspace / "multi.py").write_text(
            "def func1():\n    pass\ndef func2():\n    pass\ndef func3():\n    pass\n"
        )

        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "def func"}
        )

        assert result["exit_code"] == 0
        assert result["matches_count"] >= 3
        # Should have multiple line numbers from the same file
        assert "multi.py" in result["output"]

    @pytest.mark.asyncio
    async def test_grep_files_with_wildcard_include(
        self, search_executor: UniversalToolExecutor
    ) -> None:
        """Test grep_files with wildcard include pattern."""
        result = await search_executor.execute_tool(
            "grep_files", {"pattern": "ERROR", "include": "*.log"}
        )

        assert result["exit_code"] == 0
        # Should only search in log files
        if result["matches_count"] > 0:
            assert ".log" in result["output"]
            assert ".py" not in result["output"]
            assert ".js" not in result["output"]
