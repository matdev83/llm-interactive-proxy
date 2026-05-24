"""TDD tests for Droid->Codex tool translation.

These tests define the expected behavior of the DroidToolTranslator class
which translates Factory Droid tool calls to OpenAI Codex format.

Test isolation: All tests in this file are auto-marked with @pytest.mark.codex
by conftest.py and excluded from default pytest runs.
"""

import pytest


class TestDroidToolTranslatorRead:
    """TDD tests for Read->read_file translation."""

    def test_translate_read_to_read_file_basic(self):
        """Read with file_path should translate to read_file with path."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Read", {"file_path": "/path/to/file.py"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments

        assert tool_name == "read_file"
        assert args["path"] == "/path/to/file.py"

    def test_translate_read_with_offset_limit(self):
        """Read with offset/limit should translate to start_line/end_line."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Read", {"file_path": "/file.py", "offset": 10, "limit": 50}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments

        assert tool_name == "read_file"
        assert args["path"] == "/file.py"
        assert args["start_line"] == 10
        assert args["end_line"] == 60  # offset + limit

    def test_translate_read_with_only_offset(self):
        """Read with only offset (no limit) should set start_line only."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Read", {"file_path": "/file.py", "offset": 100}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "read_file"
        assert args["start_line"] == 100
        assert "end_line" not in args

    def test_translate_read_with_only_limit(self):
        """Read with only limit (no offset) should read from start."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Read", {"file_path": "/file.py", "limit": 100}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "read_file"
        assert args.get("start_line", 1) == 1  # Default to start
        assert args["end_line"] == 100

    def test_translate_read_windows_path(self):
        """Read should handle Windows-style paths."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Read", {"file_path": "C:\\Users\\test\\file.py"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "read_file"
        assert args["path"] == "C:\\Users\\test\\file.py"


class TestDroidToolTranslatorLS:
    """TDD tests for LS->list_dir translation."""

    def test_translate_ls_to_list_dir_basic(self):
        """LS with directory_path should translate to list_dir with path."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call("LS", {"directory_path": "/src"})
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "list_dir"
        assert args["path"] == "/src"

    def test_translate_ls_without_path(self):
        """LS without directory_path should default to current directory."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call("LS", {})
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "list_dir"
        assert args["path"] == "."

    def test_translate_ls_with_ignore_patterns(self):
        """LS with ignorePatterns should still translate (patterns handled separately)."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "LS", {"directory_path": "/src", "ignorePatterns": ["*.pyc", "__pycache__"]}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "list_dir"
        assert args["path"] == "/src"

    def test_translate_ls_windows_path(self):
        """LS should handle Windows-style paths."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "LS", {"directory_path": "C:\\Users\\test\\project"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "list_dir"
        assert args["path"] == "C:\\Users\\test\\project"


class TestDroidToolTranslatorExecute:
    """TDD tests for Execute->shell translation."""

    def test_translate_execute_to_shell_basic(self):
        """Execute with command string should become shell with array."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Execute", {"command": "pytest tests/ -v"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "shell"
        assert args["command"] == ["pytest", "tests/", "-v"]

    def test_translate_execute_with_quotes(self):
        """Execute should handle quoted arguments correctly."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Execute", {"command": 'echo "hello world"'}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "shell"
        assert args["command"] == ["echo", "hello world"]

    def test_translate_execute_with_cwd(self):
        """Execute with cwd should translate to workdir."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Execute", {"command": "npm install", "cwd": "/project"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "shell"
        assert args["command"] == ["npm", "install"]
        assert args["workdir"] == "/project"

    def test_translate_execute_single_command(self):
        """Execute with single command should work."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call("Execute", {"command": "pwd"})
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "shell"
        assert args["command"] == ["pwd"]

    def test_translate_execute_complex_command(self):
        """Execute should handle complex commands with pipes and redirects."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Execute", {"command": "ls -la | grep py"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "shell"
        # shlex.split handles this as separate tokens
        assert args["command"] == ["ls", "-la", "|", "grep", "py"]


class TestDroidToolTranslatorGrep:
    """TDD tests for Grep->grep_files translation."""

    def test_translate_grep_to_grep_files_basic(self):
        """Grep with pattern should translate to grep_files."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call("Grep", {"pattern": "def test_"})
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "grep_files"
        assert args["pattern"] == "def test_"

    def test_translate_grep_with_path(self):
        """Grep with path should pass through."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Grep", {"pattern": "import", "path": "src/"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "grep_files"
        assert args["pattern"] == "import"
        assert args["path"] == "src/"

    def test_translate_grep_with_type(self):
        """Grep with type should convert to file_patterns."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Grep", {"pattern": "class", "file_pattern": "*.py"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "grep_files"
        assert args["pattern"] == "class"
        assert args["file_patterns"] == ["*.py"]

    def test_translate_grep_with_glob(self):
        """Grep with glob should convert to file_patterns."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Grep", {"pattern": "TODO", "file_pattern": "**/*.md"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "grep_files"
        assert args["pattern"] == "TODO"
        assert args["file_patterns"] == ["**/*.md"]

    def test_translate_grep_with_file_pattern_max_results(self):
        """Grep with file_pattern and max_results should map correctly."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Grep",
            {
                "pattern": "error",
                "file_pattern": "*.log",
                "max_results": 100,
            },
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "grep_files"
        assert args["pattern"] == "error"
        assert args["file_patterns"] == ["*.log"]
        assert args["max_results"] == 100


class TestDroidToolTranslatorGlob:
    """TDD tests for Glob->grep_files translation."""

    def test_translate_glob_to_grep_files_basic(self):
        """Glob should map to grep_files with file_patterns."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call("Glob", {"pattern": "**/*.py"})
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "grep_files"
        assert args["pattern"] == "**/*.py"
        assert args["file_patterns"] == ["**/*.py"]

    def test_translate_glob_with_max_results(self):
        """Glob should propagate max_results when present."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Glob", {"pattern": "*.md", "max_results": 25}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "grep_files"
        assert args["pattern"] == "*.md"
        assert args["file_patterns"] == ["*.md"]
        assert args["max_results"] == 25


class TestDroidToolTranslatorPatchTools:
    """TDD tests for Edit/Create->apply_patch translation."""

    def test_reverse_translate_apply_patch_returns_result_not_tuple(self):
        """Codex apply_patch reverse path must return ReverseTranslationResult."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
            ReverseTranslationResult,
        )

        translator = DroidToolTranslator()
        result = translator.translate_codex_to_droid(
            "apply_patch",
            {
                "file_path": "/x.py",
                "content": "diff",
                "is_new_file": False,
            },
        )
        assert isinstance(result, ReverseTranslationResult)
        assert not isinstance(result, tuple)
        assert result.droid_tool_name == "Edit"
        assert result.droid_arguments["file_path"] == "/x.py"
        assert result.droid_arguments["new_str"] == "diff"

    def test_translate_edit_to_apply_patch(self):
        """Edit should map to apply_patch with file_path and content."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Edit",
            {
                "file_path": "/project/app.py",
                "old_str": "print('old')",
                "new_str": "print('new')",
                "content": "print('new')",
            },
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "apply_patch"
        assert args["file_path"] == "/project/app.py"
        assert args["old_str"] == ""
        assert args["new_str"] == "print('new')"

    def test_translate_create_to_apply_patch(self):
        """Create should map to apply_patch with is_new_file marker."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "Create", {"file_path": "/project/new.txt", "content": "hello"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "apply_patch"
        assert args["file_path"] == "/project/new.txt"
        assert args["content"] == "hello"
        assert args["is_new_file"] is True


class TestProxySideTools:
    """TDD tests for proxy-handled tools (no Codex equivalent)."""

    def test_todowrite_handled_proxy_side(self):
        """TodoWrite should return proxy marker."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "TodoWrite", {"todos": [{"id": "1", "content": "Test task"}]}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "__proxy_todo_write"
        assert args["todos"] == [{"id": "1", "content": "Test task"}]

    def test_websearch_handled_proxy_side(self):
        """WebSearch should return proxy marker."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "WebSearch", {"query": "python asyncio tutorial"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "__proxy_web_search"
        assert args["query"] == "python asyncio tutorial"

    def test_fetchurl_handled_proxy_side(self):
        """FetchUrl should return proxy marker."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "FetchUrl", {"url": "https://example.com"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "__proxy_fetch_url"
        assert args["url"] == "https://example.com"

    def test_exitspecmode_handled_proxy_side(self):
        """ExitSpecMode should return proxy marker."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.translate_tool_call(
            "ExitSpecMode", {"plan": "Implement feature X", "title": "Feature X"}
        )
        tool_name, args = result.codex_tool_name, result.codex_arguments
        assert tool_name == "__proxy_exit_spec_mode"
        assert args["plan"] == "Implement feature X"
        assert args["title"] == "Feature X"

    def test_unknown_tool_raises_error(self):
        """Unknown tool should raise ValueError."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        with pytest.raises(ValueError, match="Unknown Droid tool"):
            translator.translate_tool_call("UnknownTool", {"arg": "value"})
