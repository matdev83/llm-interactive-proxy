"""
Unit tests for assessment prompt loader fallback functionality.

These tests verify that the system gracefully falls back to hardcoded prompts
when files are missing, corrupted, or empty.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.core.services.assessment_prompt_loader import (
    FALLBACK_RESPONSE_SCHEMA,
    FALLBACK_STEERING_TEMPLATE,
    FALLBACK_SYSTEM_PROMPT,
    FALLBACK_TASK_PROMPT,
    AssessmentPromptLoader,
)


class TestAssessmentPromptFallbacks:
    """Test cases for prompt loader fallback functionality."""

    def test_fallback_when_directory_missing(self):
        """Test fallback when entire prompts directory is missing."""
        # Arrange
        loader = AssessmentPromptLoader("/nonexistent/directory")

        # Act
        loader.load_prompts()

        # Assert
        assert loader.is_loaded
        assert loader.system_prompt == FALLBACK_SYSTEM_PROMPT
        assert loader.task_prompt == FALLBACK_TASK_PROMPT
        assert loader.steering_template == FALLBACK_STEERING_TEMPLATE
        assert loader.response_schema == FALLBACK_RESPONSE_SCHEMA

    def test_fallback_when_all_files_missing(self):
        """Test fallback when prompt directory exists but all files are missing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            loader = AssessmentPromptLoader(temp_dir)

            # Act
            loader.load_prompts()

            # Assert
            assert loader.is_loaded
            assert loader.system_prompt == FALLBACK_SYSTEM_PROMPT
            assert loader.task_prompt == FALLBACK_TASK_PROMPT
            assert loader.steering_template == FALLBACK_STEERING_TEMPLATE
            assert loader.response_schema == FALLBACK_RESPONSE_SCHEMA

    def test_fallback_when_system_prompt_empty(self):
        """Test fallback when system prompt file is empty."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            prompts_dir = Path(temp_dir)
            (prompts_dir / "system_prompt.md").write_text("")  # Empty file
            (prompts_dir / "task_prompt.md").write_text("Valid task prompt")
            (prompts_dir / "steering_message_template.md").write_text("Valid template")
            (prompts_dir / "response_schema.json").write_text(
                json.dumps(FALLBACK_RESPONSE_SCHEMA)
            )

            loader = AssessmentPromptLoader(temp_dir)

            # Act
            loader.load_prompts()

            # Assert
            assert loader.system_prompt == FALLBACK_SYSTEM_PROMPT  # Fallback used
            assert loader.task_prompt == "Valid task prompt"  # File used
            assert loader.steering_template == "Valid template"  # File used

    def test_fallback_when_task_prompt_empty(self):
        """Test fallback when task prompt file is empty."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            prompts_dir = Path(temp_dir)
            (prompts_dir / "system_prompt.md").write_text("Valid system prompt")
            (prompts_dir / "task_prompt.md").write_text("")  # Empty file
            (prompts_dir / "steering_message_template.md").write_text("Valid template")
            (prompts_dir / "response_schema.json").write_text(
                json.dumps(FALLBACK_RESPONSE_SCHEMA)
            )

            loader = AssessmentPromptLoader(temp_dir)

            # Act
            loader.load_prompts()

            # Assert
            assert loader.system_prompt == "Valid system prompt"  # File used
            assert loader.task_prompt == FALLBACK_TASK_PROMPT  # Fallback used
            assert loader.steering_template == "Valid template"  # File used

    def test_fallback_when_steering_template_empty(self):
        """Test fallback when steering template file is empty."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            prompts_dir = Path(temp_dir)
            (prompts_dir / "system_prompt.md").write_text("Valid system prompt")
            (prompts_dir / "task_prompt.md").write_text("Valid task prompt")
            (prompts_dir / "steering_message_template.md").write_text("")  # Empty file
            (prompts_dir / "response_schema.json").write_text(
                json.dumps(FALLBACK_RESPONSE_SCHEMA)
            )

            loader = AssessmentPromptLoader(temp_dir)

            # Act
            loader.load_prompts()

            # Assert
            assert loader.system_prompt == "Valid system prompt"  # File used
            assert loader.task_prompt == "Valid task prompt"  # File used
            assert (
                loader.steering_template == FALLBACK_STEERING_TEMPLATE
            )  # Fallback used

    def test_fallback_when_response_schema_empty(self):
        """Test fallback when response schema file is empty."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            prompts_dir = Path(temp_dir)
            (prompts_dir / "system_prompt.md").write_text("Valid system prompt")
            (prompts_dir / "task_prompt.md").write_text("Valid task prompt")
            (prompts_dir / "steering_message_template.md").write_text("Valid template")
            (prompts_dir / "response_schema.json").write_text("")  # Empty file

            loader = AssessmentPromptLoader(temp_dir)

            # Act
            loader.load_prompts()

            # Assert
            assert loader.system_prompt == "Valid system prompt"  # File used
            assert loader.task_prompt == "Valid task prompt"  # File used
            assert loader.steering_template == "Valid template"  # File used
            assert loader.response_schema == FALLBACK_RESPONSE_SCHEMA  # Fallback used

    def test_fallback_when_response_schema_invalid_json(self):
        """Test fallback when response schema contains invalid JSON."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            prompts_dir = Path(temp_dir)
            (prompts_dir / "system_prompt.md").write_text("Valid system prompt")
            (prompts_dir / "task_prompt.md").write_text("Valid task prompt")
            (prompts_dir / "steering_message_template.md").write_text("Valid template")
            (prompts_dir / "response_schema.json").write_text("invalid json content")

            loader = AssessmentPromptLoader(temp_dir)

            # Act
            loader.load_prompts()

            # Assert
            assert loader.response_schema == FALLBACK_RESPONSE_SCHEMA  # Fallback used

    def test_fallback_when_response_schema_missing_properties(self):
        """Test fallback when response schema is missing required properties."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            prompts_dir = Path(temp_dir)
            (prompts_dir / "system_prompt.md").write_text("Valid system prompt")
            (prompts_dir / "task_prompt.md").write_text("Valid task prompt")
            (prompts_dir / "steering_message_template.md").write_text("Valid template")

            # Schema missing 'confidence' property
            invalid_schema = {
                "type": "object",
                "properties": {"reasoning": {"type": "string"}},
            }
            (prompts_dir / "response_schema.json").write_text(
                json.dumps(invalid_schema)
            )

            loader = AssessmentPromptLoader(temp_dir)

            # Act
            loader.load_prompts()

            # Assert
            assert loader.response_schema == FALLBACK_RESPONSE_SCHEMA  # Fallback used

    def test_fallback_when_response_schema_not_object(self):
        """Test fallback when response schema is not a JSON object."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            prompts_dir = Path(temp_dir)
            (prompts_dir / "system_prompt.md").write_text("Valid system prompt")
            (prompts_dir / "task_prompt.md").write_text("Valid task prompt")
            (prompts_dir / "steering_message_template.md").write_text("Valid template")
            (prompts_dir / "response_schema.json").write_text('["not", "an", "object"]')

            loader = AssessmentPromptLoader(temp_dir)

            # Act
            loader.load_prompts()

            # Assert
            assert loader.response_schema == FALLBACK_RESPONSE_SCHEMA  # Fallback used

    @patch("builtins.open", side_effect=PermissionError("Permission denied"))
    def test_fallback_when_file_permission_error(self, mock_open):
        """Test fallback when files exist but can't be read due to permissions."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            prompts_dir = Path(temp_dir)
            (prompts_dir / "system_prompt.md").write_text("Valid system prompt")
            (prompts_dir / "task_prompt.md").write_text("Valid task prompt")
            (prompts_dir / "steering_message_template.md").write_text("Valid template")
            (prompts_dir / "response_schema.json").write_text(
                json.dumps(FALLBACK_RESPONSE_SCHEMA)
            )

            loader = AssessmentPromptLoader(temp_dir)

            # Act
            loader.load_prompts()

            # Assert - All should fall back due to permission errors
            assert loader.system_prompt == FALLBACK_SYSTEM_PROMPT
            assert loader.task_prompt == FALLBACK_TASK_PROMPT
            assert loader.steering_template == FALLBACK_STEERING_TEMPLATE
            assert loader.response_schema == FALLBACK_RESPONSE_SCHEMA

    def test_mixed_fallback_scenario(self):
        """Test scenario where some files exist and others need fallback."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            prompts_dir = Path(temp_dir)
            (prompts_dir / "system_prompt.md").write_text("Custom system prompt")
            # task_prompt.md missing - should use fallback
            (prompts_dir / "steering_message_template.md").write_text(
                "Custom steering: {reasoning}"
            )
            # response_schema.json missing - should use fallback

            loader = AssessmentPromptLoader(temp_dir)

            # Act
            loader.load_prompts()

            # Assert
            assert loader.system_prompt == "Custom system prompt"  # File used
            assert loader.task_prompt == FALLBACK_TASK_PROMPT  # Fallback used
            assert (
                loader.steering_template == "Custom steering: {reasoning}"
            )  # File used
            assert loader.response_schema == FALLBACK_RESPONSE_SCHEMA  # Fallback used

    def test_fallback_constants_match_original_content(self):
        """Test that fallback constants match the original file content."""
        # This test ensures the fallback constants are kept in sync with file content

        # Test system prompt
        assert "sophisticated AI diagnostic agent" in FALLBACK_SYSTEM_PROMPT
        assert "Repetitive Actions" in FALLBACK_SYSTEM_PROMPT
        assert "Cognitive Loop" in FALLBACK_SYSTEM_PROMPT

        # Test task prompt
        assert "analyze the conversation history" in FALLBACK_TASK_PROMPT
        assert "JSON format" in FALLBACK_TASK_PROMPT

        # Test steering template
        assert "[SYSTEM NOTICE]" in FALLBACK_STEERING_TEMPLATE
        assert "{reasoning}" in FALLBACK_STEERING_TEMPLATE

        # Test response schema
        assert FALLBACK_RESPONSE_SCHEMA["type"] == "object"
        assert "reasoning" in FALLBACK_RESPONSE_SCHEMA["properties"]
        assert "confidence" in FALLBACK_RESPONSE_SCHEMA["properties"]
        assert FALLBACK_RESPONSE_SCHEMA["required"] == ["reasoning", "confidence"]

    def test_logging_warnings_for_fallbacks(self):
        """Test that appropriate warnings are logged when fallbacks are used."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Arrange
            loader = AssessmentPromptLoader(temp_dir)  # Empty directory

            # Act
            with patch(
                "src.core.services.assessment_prompt_loader.logger"
            ) as mock_logger:
                loader.load_prompts()

                # Assert - Should have warning calls for each missing file
                warning_calls = list(mock_logger.warning.call_args_list)
                assert (
                    len(warning_calls) >= 4
                )  # At least one warning for each file type

                # Check that warnings mention fallback usage
                warning_messages = [str(call) for call in warning_calls]
                assert any("fallback" in msg.lower() for msg in warning_messages)
