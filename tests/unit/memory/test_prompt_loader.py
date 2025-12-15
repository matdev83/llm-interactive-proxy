"""Unit tests for PromptLoader."""

from __future__ import annotations

import tempfile
from pathlib import Path

from src.core.memory.prompt_loader import (
    PromptLoader,
)


class TestPromptLoader:
    """Tests for PromptLoader."""

    def test_loads_default_summary_prompt(self) -> None:
        """Test loading default summary prompt when no file exists."""
        loader = PromptLoader(prompts_dir="/nonexistent/path")
        prompt = loader.load_summary_prompt()

        assert "session_transcript" in prompt
        assert "max_tokens" in prompt

    def test_loads_default_context_prompt(self) -> None:
        """Test loading default context prompt when no file exists."""
        loader = PromptLoader(prompts_dir="/nonexistent/path")
        prompt = loader.load_context_prompt()

        assert "user_prompt" in prompt
        assert "session_summaries" in prompt

    def test_loads_custom_summary_prompt(self) -> None:
        """Test loading custom summary prompt from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "custom_summary.md"
            prompt_file.write_text("Custom summary prompt: {session_transcript}")

            loader = PromptLoader(summary_prompt_path=str(prompt_file))
            prompt = loader.load_summary_prompt()

            assert "Custom summary prompt" in prompt

    def test_loads_custom_context_prompt(self) -> None:
        """Test loading custom context prompt from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "custom_context.md"
            prompt_file.write_text("Custom context prompt: {user_prompt}")

            loader = PromptLoader(context_prompt_path=str(prompt_file))
            prompt = loader.load_context_prompt()

            assert "Custom context prompt" in prompt

    def test_loads_from_prompts_dir(self) -> None:
        """Test loading prompt from prompts directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_file = Path(tmpdir) / "memory_summary.md"
            prompt_file.write_text("Directory prompt: {session_transcript}")

            loader = PromptLoader(prompts_dir=tmpdir)
            prompt = loader.load_summary_prompt()

            assert "Directory prompt" in prompt

    def test_caches_loaded_prompts(self) -> None:
        """Test that prompts are cached after first load."""
        loader = PromptLoader(prompts_dir="/nonexistent/path")

        prompt1 = loader.load_summary_prompt()
        prompt2 = loader.load_summary_prompt()

        assert prompt1 is prompt2

    def test_substitute_variables(self) -> None:
        """Test variable substitution in templates."""
        loader = PromptLoader()
        template = "Hello {name}, your ID is {id}."
        variables = {"name": "Alice", "id": "123"}

        result = loader.substitute_variables(template, variables)

        assert result == "Hello Alice, your ID is 123."

    def test_substitute_missing_variables(self) -> None:
        """Test that missing variables are left as-is."""
        loader = PromptLoader()
        template = "Hello {name}, your ID is {id}."
        variables = {"name": "Alice"}

        result = loader.substitute_variables(template, variables)

        assert "Alice" in result
        # Missing variables remain as {var} since we only convert known keys
        assert "{id}" in result

    def test_substitute_all_supported_variables(self) -> None:
        """Test substitution of all supported template variables."""
        loader = PromptLoader()
        template = """
        Transcript: {session_transcript}
        User: {user_id}
        Session: {session_id}
        Project: {project_root}
        Model: {model}
        Branch: {branch}
        Head: {head_sha}
        Timestamp: {analysis_timestamp}
        Schema: {summary_schema_version}
        Prompt: {summary_prompt_version}
        Tokens: {max_tokens}
        """
        variables = {
            "session_transcript": "Hello",
            "user_id": "user-1",
            "session_id": "sess-1",
            "project_root": "/home/user",
            "model": "gpt-4o",
            "branch": "main",
            "head_sha": "abc123",
            "analysis_timestamp": "2025-01-01",
            "summary_schema_version": "v1",
            "summary_prompt_version": "v1",
            "max_tokens": "1000",
        }

        result = loader.substitute_variables(template, variables)

        for value in variables.values():
            assert value in result

    def test_validate_paths_valid(self) -> None:
        """Test path validation with valid paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_file = Path(tmpdir) / "summary.md"
            context_file = Path(tmpdir) / "context.md"
            summary_file.write_text("Summary")
            context_file.write_text("Context")

            loader = PromptLoader(
                summary_prompt_path=str(summary_file),
                context_prompt_path=str(context_file),
            )
            errors = loader.validate_paths()

            assert len(errors) == 0

    def test_validate_paths_invalid(self) -> None:
        """Test path validation with invalid paths."""
        loader = PromptLoader(
            summary_prompt_path="/nonexistent/summary.md",
            context_prompt_path="/nonexistent/context.md",
        )
        errors = loader.validate_paths()

        assert len(errors) == 2
        assert any("Summary" in e for e in errors)
        assert any("Context" in e for e in errors)

    def test_validate_paths_none(self) -> None:
        """Test path validation with no custom paths."""
        loader = PromptLoader()
        errors = loader.validate_paths()

        assert len(errors) == 0
