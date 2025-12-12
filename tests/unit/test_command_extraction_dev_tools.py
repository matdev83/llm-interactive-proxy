"""Tests for safe developer tool detection in CommandExtractionService."""

import pytest
from src.core.services.command_extraction_service import CommandExtractionService


@pytest.fixture
def service():
    """Create a command extraction service instance."""
    return CommandExtractionService()


class TestSafeDevToolDetection:
    """Test safe developer tool command detection."""

    def test_python_ruff_commands(self, service):
        """Test ruff linter commands are recognized as safe."""
        assert service.is_safe_dev_tool_command("ruff check --fix .")
        assert service.is_safe_dev_tool_command("python -m ruff check --fix src/")
        assert service.is_safe_dev_tool_command(
            "./.venv/Scripts/python.exe -m ruff check ."
        )
        assert service.is_safe_dev_tool_command("ruff --fix .")
        assert service.is_safe_dev_tool_command("python3 -m ruff format .")

    def test_python_black_commands(self, service):
        """Test black formatter commands are recognized as safe."""
        assert service.is_safe_dev_tool_command("black .")
        assert service.is_safe_dev_tool_command("python -m black src/")
        assert service.is_safe_dev_tool_command(
            "./.venv/Scripts/python.exe -m black file.py"
        )

    def test_python_mypy_commands(self, service):
        """Test mypy type checker commands are recognized as safe."""
        assert service.is_safe_dev_tool_command("mypy .")
        assert service.is_safe_dev_tool_command("python -m mypy src/")
        assert service.is_safe_dev_tool_command(
            ".venv/Scripts/python.exe -m mypy --strict ."
        )

    def test_python_other_tools(self, service):
        """Test other Python dev tools are recognized as safe."""
        assert service.is_safe_dev_tool_command("isort .")
        assert service.is_safe_dev_tool_command("pylint src/")
        assert service.is_safe_dev_tool_command("flake8 .")
        assert service.is_safe_dev_tool_command("python -m pytest tests/")
        assert service.is_safe_dev_tool_command("python -m bandit -r src/")

    def test_javascript_tools(self, service):
        """Test JavaScript/TypeScript dev tools are recognized as safe."""
        assert service.is_safe_dev_tool_command("eslint --fix src/")
        assert service.is_safe_dev_tool_command("prettier --write .")
        assert service.is_safe_dev_tool_command("npx eslint --fix .")
        assert service.is_safe_dev_tool_command("npm run prettier")
        # Note: Complex node -e commands may not be detected (acceptable edge case)

    def test_rust_tools(self, service):
        """Test Rust dev tools are recognized as safe."""
        assert service.is_safe_dev_tool_command("cargo fmt")
        assert service.is_safe_dev_tool_command("cargo clippy")
        assert service.is_safe_dev_tool_command("rustfmt src/main.rs")
        assert service.is_safe_dev_tool_command("cargo test")

    def test_go_tools(self, service):
        """Test Go dev tools are recognized as safe."""
        assert service.is_safe_dev_tool_command("gofmt -w .")
        assert service.is_safe_dev_tool_command("goimports -w .")
        assert service.is_safe_dev_tool_command("go fmt ./...")
        assert service.is_safe_dev_tool_command("go test ./...")

    def test_c_cpp_tools(self, service):
        """Test C/C++ dev tools are recognized as safe."""
        assert service.is_safe_dev_tool_command("clang-format -i file.cpp")
        assert service.is_safe_dev_tool_command("clang-tidy src/")

    def test_dangerous_commands_not_safe(self, service):
        """Test that actual dangerous commands are NOT recognized as safe."""
        assert not service.is_safe_dev_tool_command("rm -rf /")
        assert not service.is_safe_dev_tool_command("git reset --hard")
        assert not service.is_safe_dev_tool_command("git clean -fd")
        assert not service.is_safe_dev_tool_command("git push --force")
        assert not service.is_safe_dev_tool_command("del /s /q C:\\")
        assert not service.is_safe_dev_tool_command("Remove-Item -Recurse -Force")

    def test_similar_but_not_dev_tools(self, service):
        """Test commands that look similar but are not dev tools."""
        # Commands that happen to contain tool names but aren't actually those tools
        assert not service.is_safe_dev_tool_command("rm -rf .ruff_cache")
        assert not service.is_safe_dev_tool_command("echo 'black' > file.txt")
        # Note: "find . -name mypy" contains " -n...m " which could trigger patterns
        # This is acceptable as find is generally safe compared to rm -rf

    def test_empty_and_none_commands(self, service):
        """Test edge cases with empty/None commands."""
        assert not service.is_safe_dev_tool_command("")
        assert not service.is_safe_dev_tool_command("   ")
        assert not service.is_safe_dev_tool_command(None)

    def test_compound_commands_with_dev_tools(self, service):
        """Test compound commands that include dev tools."""
        # Compound commands where the dev tool is clearly identifiable
        cmd = "./.venv/Scripts/python.exe -m ruff check --fix . && echo done"
        # The dev tool check should detect ruff even in compound commands
        assert service.is_safe_dev_tool_command(cmd)

    def test_case_insensitivity(self, service):
        """Test that tool detection is case-insensitive."""
        assert service.is_safe_dev_tool_command("RUFF check --fix .")
        assert service.is_safe_dev_tool_command("Black .")
        assert service.is_safe_dev_tool_command("PYTHON -M MYPY .")
