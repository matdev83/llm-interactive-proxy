"""TDD tests for Codex->Droid result formatting.

These tests define the expected behavior of the result formatting
which translates Codex tool results back to Droid's expected format.

Test isolation: All tests in this file are auto-marked with @pytest.mark.codex
by conftest.py and excluded from default pytest runs.
"""


class TestDroidResultFormatter:
    """TDD tests for Codex->Droid result formatting."""

    def test_format_read_file_success(self):
        """Successful read_file result should be plain content."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.format_result(
            {"output": "file content here", "exit_code": 0},
            _original_tool="Read",
        )
        assert result == "file content here"

    def test_format_error_result(self):
        """Error should be formatted as 'Error: <message>'."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.format_result(
            {"error": "File not found", "exit_code": 1},
            _original_tool="Read",
        )
        assert result.startswith("Error: ")
        assert "File not found" in result

    def test_format_shell_success(self):
        """Successful shell command should return output."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.format_result(
            {"output": "test_file.py\ntest_module.py", "exit_code": 0},
            _original_tool="Execute",
        )
        assert result == "test_file.py\ntest_module.py"

    def test_format_content_field(self):
        """Result with 'content' field should extract it."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.format_result(
            {"content": "Directory listing:\n- file1.py\n- file2.py"},
            _original_tool="LS",
        )
        assert result == "Directory listing:\n- file1.py\n- file2.py"

    def test_format_result_field(self):
        """Result with 'result' field should extract it."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.format_result(
            {"result": "Search completed: 5 matches found"},
            _original_tool="Grep",
        )
        assert result == "Search completed: 5 matches found"

    def test_format_empty_output(self):
        """Empty output should return empty string."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.format_result(
            {"output": "", "exit_code": 0},
            _original_tool="Execute",
        )
        assert result == ""

    def test_format_dict_fallback(self):
        """Unknown result structure should stringify."""
        from src.connectors._openai_codex_droid_tool_translator import (
            DroidToolTranslator,
        )

        translator = DroidToolTranslator()
        result = translator.format_result(
            {"custom_field": "value", "other": 123},
            _original_tool="Unknown",
        )
        # Should have some string representation
        assert isinstance(result, str)
        assert "custom_field" in result or "value" in result
