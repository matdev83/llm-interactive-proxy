"""
Unit tests for the assessment prompt loader.

These tests verify that prompts are correctly loaded from Markdown files.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from src.core.services.assessment_prompt_loader import AssessmentPromptLoader


@pytest.fixture
def temp_prompts_dir():
    """Create a temporary directory with test prompt files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        prompts_dir = Path(temp_dir)

        # Create system prompt file
        system_prompt_file = prompts_dir / "system_prompt.md"
        system_prompt_file.write_text("Test system prompt for assessment")

        # Create task prompt file
        task_prompt_file = prompts_dir / "task_prompt.md"
        task_prompt_file.write_text("Test task prompt for assessment")

        # Create response schema file
        schema_file = prompts_dir / "response_schema.json"
        schema = {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["reasoning", "confidence"],
        }
        schema_file.write_text(json.dumps(schema, indent=2))

        # Create steering message template file
        steering_template_file = prompts_dir / "steering_message_template.md"
        steering_template_file.write_text(
            "[SYSTEM NOTICE] Potential conversation loop detected. {reasoning}"
        )

        yield prompts_dir


class TestAssessmentPromptLoader:
    """Test cases for AssessmentPromptLoader."""

    def test_load_prompts_success(self, temp_prompts_dir):
        """Test successful prompt loading."""
        # Arrange
        loader = AssessmentPromptLoader(str(temp_prompts_dir))

        # Act
        loader.load_prompts()

        # Assert
        assert loader.is_loaded
        assert loader.system_prompt == "Test system prompt for assessment"
        assert loader.task_prompt == "Test task prompt for assessment"
        assert (
            loader.steering_template
            == "[SYSTEM NOTICE] Potential conversation loop detected. {reasoning}"
        )
        assert loader.response_schema["type"] == "object"
        assert "reasoning" in loader.response_schema["properties"]
        assert "confidence" in loader.response_schema["properties"]

    def test_load_prompts_missing_system_prompt(self, temp_prompts_dir):
        """Test fallback when system prompt file is missing."""
        # Arrange
        loader = AssessmentPromptLoader(str(temp_prompts_dir))
        (temp_prompts_dir / "system_prompt.md").unlink()  # Remove file

        # Act
        loader.load_prompts()

        # Assert - Should use fallback, not raise exception
        assert loader.is_loaded
        assert "sophisticated AI diagnostic agent" in loader.system_prompt

    def test_load_prompts_missing_task_prompt(self, temp_prompts_dir):
        """Test fallback when task prompt file is missing."""
        # Arrange
        loader = AssessmentPromptLoader(str(temp_prompts_dir))
        (temp_prompts_dir / "task_prompt.md").unlink()  # Remove file

        # Act
        loader.load_prompts()

        # Assert - Should use fallback, not raise exception
        assert loader.is_loaded
        assert "analyze the conversation history" in loader.task_prompt

    def test_load_prompts_missing_schema(self, temp_prompts_dir):
        """Test fallback when response schema file is missing."""
        # Arrange
        loader = AssessmentPromptLoader(str(temp_prompts_dir))
        (temp_prompts_dir / "response_schema.json").unlink()  # Remove file

        # Act
        loader.load_prompts()

        # Assert - Should use fallback, not raise exception
        assert loader.is_loaded
        assert loader.response_schema["type"] == "object"
        assert "reasoning" in loader.response_schema["properties"]

    def test_load_prompts_missing_steering_template(self, temp_prompts_dir):
        """Test fallback when steering message template file is missing."""
        # Arrange
        loader = AssessmentPromptLoader(str(temp_prompts_dir))
        (temp_prompts_dir / "steering_message_template.md").unlink()  # Remove file

        # Act
        loader.load_prompts()

        # Assert - Should use fallback, not raise exception
        assert loader.is_loaded
        assert "[SYSTEM NOTICE]" in loader.steering_template

    def test_load_prompts_empty_system_prompt(self, temp_prompts_dir):
        """Test fallback when system prompt is empty."""
        # Arrange
        loader = AssessmentPromptLoader(str(temp_prompts_dir))
        (temp_prompts_dir / "system_prompt.md").write_text("")  # Empty file

        # Act
        loader.load_prompts()

        # Assert - Should use fallback, not raise exception
        assert loader.is_loaded
        assert "sophisticated AI diagnostic agent" in loader.system_prompt

    def test_load_prompts_invalid_json_schema(self, temp_prompts_dir):
        """Test fallback when response schema is invalid JSON."""
        # Arrange
        loader = AssessmentPromptLoader(str(temp_prompts_dir))
        (temp_prompts_dir / "response_schema.json").write_text("invalid json")

        # Act
        loader.load_prompts()

        # Assert - Should use fallback, not raise exception
        assert loader.is_loaded
        assert loader.response_schema["type"] == "object"

    def test_load_prompts_missing_schema_properties(self, temp_prompts_dir):
        """Test error when schema is missing required properties."""
        # Arrange
        loader = AssessmentPromptLoader(str(temp_prompts_dir))
        invalid_schema = {
            "type": "object",
            "properties": {"reasoning": {"type": "string"}},
        }
        (temp_prompts_dir / "response_schema.json").write_text(
            json.dumps(invalid_schema)
        )

        # Act
        loader.load_prompts()

        # Assert - Should use fallback, not raise exception
        assert loader.is_loaded
        assert "confidence" in loader.response_schema["properties"]

    def test_access_prompts_before_loading(self):
        """Test error when accessing prompts before loading."""
        # Arrange
        loader = AssessmentPromptLoader()

        # Act & Assert
        with pytest.raises(RuntimeError, match="Prompts not loaded"):
            _ = loader.system_prompt

        with pytest.raises(RuntimeError, match="Prompts not loaded"):
            _ = loader.task_prompt

        with pytest.raises(RuntimeError, match="Prompts not loaded"):
            _ = loader.response_schema

    def test_reload_prompts(self, temp_prompts_dir):
        """Test reloading prompts."""
        # Arrange
        loader = AssessmentPromptLoader(str(temp_prompts_dir))
        loader.load_prompts()
        original_prompt = loader.system_prompt

        # Modify the prompt file
        (temp_prompts_dir / "system_prompt.md").write_text("Modified system prompt")

        # Act
        loader.reload_prompts()

        # Assert
        assert loader.system_prompt == "Modified system prompt"
        assert loader.system_prompt != original_prompt

    def test_get_prompt_info_not_loaded(self):
        """Test prompt info when not loaded."""
        # Arrange
        loader = AssessmentPromptLoader()

        # Act
        info = loader.get_prompt_info()

        # Assert
        assert info.loaded is False

    def test_get_prompt_info_loaded(self, temp_prompts_dir):
        """Test prompt info when loaded."""
        # Arrange
        loader = AssessmentPromptLoader(str(temp_prompts_dir))
        loader.load_prompts()

        # Act
        info = loader.get_prompt_info()

        # Assert
        assert info.loaded is True
        assert info.prompts_dir == str(temp_prompts_dir)
        assert info.system_prompt_length > 0
        assert info.task_prompt_length > 0
        assert "reasoning" in info.schema_properties
        assert "confidence" in info.schema_properties

    def test_default_prompts_directory(self):
        """Test that default prompts directory is set correctly."""
        # Arrange & Act
        loader = AssessmentPromptLoader()

        # Assert
        import os

        expected_path = os.path.normpath("config/prompts/loop_assessment_prompts")
        actual_path = os.path.normpath(str(loader.prompts_dir))
        assert actual_path == expected_path


class TestAssessmentPromptsModule:
    """Test cases for the assessment_prompts module functions."""

    @patch("src.core.services.assessment_prompts.get_prompt_loader")
    def test_initialize_prompts(self, mock_get_loader):
        """Test prompt initialization."""
        # Arrange
        mock_loader = Mock()
        mock_loader.is_loaded = False
        mock_get_loader.return_value = mock_loader

        from src.core.services.assessment_prompts import initialize_prompts

        # Act
        initialize_prompts()

        # Assert
        mock_loader.load_prompts.assert_called_once()

    @patch("src.core.services.assessment_prompts.get_prompt_loader")
    def test_initialize_prompts_already_loaded(self, mock_get_loader):
        """Test prompt initialization when already loaded."""
        # Arrange
        mock_loader = Mock()
        mock_loader.is_loaded = True
        mock_get_loader.return_value = mock_loader

        from src.core.services.assessment_prompts import initialize_prompts

        # Act
        initialize_prompts()

        # Assert
        mock_loader.load_prompts.assert_not_called()

    @patch("src.core.services.assessment_prompts.get_prompt_loader")
    def test_get_system_prompt(self, mock_get_loader):
        """Test getting system prompt."""
        # Arrange
        mock_loader = Mock()
        mock_loader.system_prompt = "Test system prompt"
        mock_get_loader.return_value = mock_loader

        from src.core.services.assessment_prompts import get_system_prompt

        # Act
        result = get_system_prompt()

        # Assert
        assert result == "Test system prompt"

    @patch("src.core.services.assessment_prompts.get_prompt_loader")
    def test_get_task_prompt(self, mock_get_loader):
        """Test getting task prompt."""
        # Arrange
        mock_loader = Mock()
        mock_loader.task_prompt = "Test task prompt"
        mock_get_loader.return_value = mock_loader

        from src.core.services.assessment_prompts import get_task_prompt

        # Act
        result = get_task_prompt()

        # Assert
        assert result == "Test task prompt"

    @patch("src.core.services.assessment_prompts.get_prompt_loader")
    def test_get_response_schema(self, mock_get_loader):
        """Test getting response schema."""
        # Arrange
        mock_loader = Mock()
        mock_loader.response_schema = {"type": "object"}
        mock_get_loader.return_value = mock_loader

        from src.core.services.assessment_prompts import get_response_schema

        # Act
        result = get_response_schema()

        # Assert
        assert result == {"type": "object"}

    @patch("src.core.services.assessment_prompts.get_prompt_loader")
    def test_get_steering_template(self, mock_get_loader):
        """Test getting steering template."""
        # Arrange
        mock_loader = Mock()
        mock_loader.steering_template = "[SYSTEM NOTICE] Test template. {reasoning}"
        mock_get_loader.return_value = mock_loader

        from src.core.services.assessment_prompts import get_steering_template

        # Act
        result = get_steering_template()

        # Assert
        assert result == "[SYSTEM NOTICE] Test template. {reasoning}"

    @patch("src.core.services.assessment_prompts.get_prompt_loader")
    def test_is_initialized(self, mock_get_loader):
        """Test checking if prompts are initialized."""
        # Arrange
        mock_loader = Mock()
        mock_loader.is_loaded = True
        mock_get_loader.return_value = mock_loader

        from src.core.services.assessment_prompts import is_initialized

        # Act
        result = is_initialized()

        # Assert
        assert result is True
