"""Unit tests for CliArgsValidator.

Tests that CliArgsValidator performs non-argparse validation on parsed arguments
and raises stable, testable exceptions when validation fails.

Requirements satisfied:
- 9.1: Unit tests for CliArgsValidator
- 1.4: Structured, testable errors from validation service

Test-Driven Development (TDD):
- These tests are written FIRST (RED phase)
- Implementation will follow to make tests pass (GREEN phase)
"""

from __future__ import annotations

import argparse
from typing import Any
from unittest.mock import patch

import pytest

# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def validator() -> Any:
    """Create a CliArgsValidator instance."""
    from src.core.cli_support.cli_args_validator import CliArgsValidator

    return CliArgsValidator()


@pytest.fixture
def args() -> argparse.Namespace:
    """Create a minimal args namespace for testing."""
    return argparse.Namespace()


# =============================================================================
# Basic Validator Tests
# =============================================================================


class TestCliArgsValidatorBasic:
    """Tests for basic CliArgsValidator functionality."""

    def test_validator_has_validate_method(self, validator: object) -> None:
        """Validator has a validate method."""
        assert hasattr(validator, "validate")
        assert callable(validator.validate)

    def test_validate_accepts_namespace(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        """Validator.validate accepts an argparse.Namespace."""
        # Should not raise for minimal args
        validator.validate(args)  # type: ignore[union-attr]

    def test_validate_returns_none(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        """Validator.validate returns None on success."""
        result = validator.validate(args)  # type: ignore[union-attr]
        assert result is None


# =============================================================================
# Auto-append first prompt filename validation
# =============================================================================


class TestAutoAppendFirstPromptFilenameValidation:
    def test_rejects_non_txt_md_extension(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        args.auto_append_first_prompt_filename = "prompt.yaml"
        with pytest.raises(ValueError, match=r"\.txt or \.md"):
            validator.validate(args)  # type: ignore[union-attr]

    def test_accepts_txt_md(self, validator: object, args: argparse.Namespace) -> None:
        args.auto_append_first_prompt_filename = "p.txt"
        validator.validate(args)  # type: ignore[union-attr]


# =============================================================================
# Random Model Replacement Validation Tests
# =============================================================================


class TestRandomModelReplacementValidation:
    """Tests for random model replacement configuration validation."""

    def test_passes_when_replacement_disabled(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        """Validation passes when replacement is not enabled."""
        args.replacement_enabled = False
        args.replacement_backend_model = None
        validator.validate(args)  # type: ignore[union-attr]

    def test_raises_when_replacement_enabled_no_model(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        """Validation raises ValueError when replacement enabled but model missing."""
        args.replacement_enabled = True
        args.replacement_backend_model = None

        with pytest.raises(ValueError) as exc_info:
            validator.validate(args)  # type: ignore[union-attr]

        assert "Replacement backend:model must be specified" in str(exc_info.value)

    def test_raises_when_replacement_model_invalid_format(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        """Validation raises ValueError when replacement model format is invalid."""
        args.replacement_enabled = True
        args.replacement_backend_model = "openai"  # Missing colon

        with pytest.raises(ValueError) as exc_info:
            validator.validate(args)  # type: ignore[union-attr]

        assert "Expected BACKEND:MODEL" in str(exc_info.value)

    @patch("src.core.cli_support.cli_args_validator.backend_registry")
    def test_raises_when_replacement_backend_not_registered(
        self, mock_registry, validator: object, args: argparse.Namespace
    ) -> None:
        """Validation raises ValueError when replacement backend is not registered."""
        args.replacement_enabled = True
        args.replacement_backend_model = "invalid:gpt-4"
        mock_registry.get_registered_backends.return_value = ["openai", "gemini"]

        with pytest.raises(ValueError) as exc_info:
            validator.validate(args)  # type: ignore[union-attr]

        assert "Invalid backend 'invalid' specified for model replacement" in str(
            exc_info.value
        )

    @patch("src.core.cli_support.cli_args_validator.backend_registry")
    def test_raises_when_replacement_target_is_model_only_selector(
        self, mock_registry, validator: object, args: argparse.Namespace
    ) -> None:
        """Replacement target must use explicit backend:model syntax."""
        args.replacement_enabled = True
        args.replacement_rules = [
            "gpt-4=openrouter/anthropic/claude-3-haiku:free",
        ]
        args.replacement_backend_model = None
        mock_registry.get_registered_backends.return_value = ["openai", "openrouter"]

        with pytest.raises(ValueError) as exc_info:
            validator.validate(args)  # type: ignore[union-attr]

        assert "backend:model" in str(exc_info.value)

    @patch("src.core.cli_support.cli_args_validator.backend_registry")
    def test_raises_when_replacement_probability_out_of_range(
        self, mock_registry, validator: object, args: argparse.Namespace
    ) -> None:
        """Validation raises ValueError when replacement probability is out of range."""
        args.replacement_enabled = True
        args.replacement_backend_model = "openai:gpt-4"
        args.replacement_probability = 1.5
        mock_registry.get_registered_backends.return_value = ["openai"]

        with pytest.raises(ValueError) as exc_info:
            validator.validate(args)  # type: ignore[union-attr]

        assert "Must be between 0.0 and 1.0" in str(exc_info.value)

    @patch("src.core.cli_support.cli_args_validator.backend_registry")
    def test_raises_when_replacement_turn_count_too_low(
        self, mock_registry, validator: object, args: argparse.Namespace
    ) -> None:
        """Validation raises ValueError when replacement turn count is less than 1."""
        args.replacement_enabled = True
        args.replacement_backend_model = "openai:gpt-4"
        args.replacement_turn_count = 0
        mock_registry.get_registered_backends.return_value = ["openai"]

        with pytest.raises(ValueError) as exc_info:
            validator.validate(args)  # type: ignore[union-attr]

        assert "Must be at least 1" in str(exc_info.value)

    @patch("src.core.cli_support.cli_args_validator.backend_registry")
    def test_passes_on_valid_replacement_config(
        self, mock_registry, validator: object, args: argparse.Namespace
    ) -> None:
        """Validation passes with full valid replacement configuration."""
        args.replacement_enabled = True
        args.replacement_backend_model = "openai:gpt-4"
        args.replacement_probability = 0.5
        args.replacement_turn_count = 3
        mock_registry.get_registered_backends.return_value = ["openai"]

        # Should not raise
        validator.validate(args)  # type: ignore[union-attr]


# =============================================================================
# Error Message Format Tests
# =============================================================================


class TestErrorMessageFormat:
    """Tests for stable, testable error messages."""

    def test_error_message_is_stable(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        """Error messages are deterministic for the same input."""
        args.replacement_enabled = True
        args.replacement_rules = None
        args.replacement_backend_model = "invalid:gpt-4o-mini"

        errors: list[str] = []
        for _ in range(3):
            with patch(
                "src.core.cli_support.cli_args_validator.backend_registry"
            ) as mock_registry:
                mock_registry.get_registered_backends.return_value = [
                    "openai",
                    "gemini",
                ]
                try:
                    validator.validate(args)  # type: ignore[union-attr]
                except ValueError as e:
                    errors.append(str(e))

        assert len(set(errors)) == 1


# =============================================================================
# Multiple Validation Tests
# =============================================================================


class TestMultipleValidations:
    """Tests for validator behavior with multiple issues."""

    def test_validator_is_reusable(self, validator: object) -> None:
        """Validator can be used multiple times."""
        args1 = argparse.Namespace(single_user_mode=False, multi_user_mode=False)
        args2 = argparse.Namespace(single_user_mode=False, multi_user_mode=False)

        validator.validate(args1)  # type: ignore[union-attr]
        validator.validate(args2)  # type: ignore[union-attr]

    def test_validator_validates_all_args(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        """Validator checks all validation rules."""
        args.single_user_mode = False
        args.multi_user_mode = False
        args.replacement_enabled = True
        args.replacement_rules = ["gpt-4o=openai:gpt-4o-mini"]
        args.replacement_backend_model = None
        args.replacement_probability = 0.5
        args.replacement_turn_count = 2

        with patch(
            "src.core.cli_support.cli_args_validator.backend_registry"
        ) as mock_registry:
            mock_registry.get_registered_backends.return_value = ["openai"]
            validator.validate(args)  # type: ignore[union-attr]


# =============================================================================
# Access Mode Validation Tests
# =============================================================================


class TestAccessModeValidation:
    """Tests for access mode validation."""

    def test_passes_when_no_access_mode_flags(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        """Validation passes when no access mode flags are specified."""
        args.single_user_mode = False
        args.multi_user_mode = False
        validator.validate(args)  # type: ignore[union-attr]

    def test_passes_when_only_single_user_mode(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        """Validation passes when only --single-user-mode is specified."""
        args.single_user_mode = True
        args.multi_user_mode = False
        validator.validate(args)  # type: ignore[union-attr]

    def test_passes_when_only_multi_user_mode(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        """Validation passes when only --multi-user-mode is specified."""
        args.single_user_mode = False
        args.multi_user_mode = True
        validator.validate(args)  # type: ignore[union-attr]

    def test_raises_when_both_flags_specified(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        """Validation raises ValueError when both access mode flags are specified."""
        args.single_user_mode = True
        args.multi_user_mode = True

        with pytest.raises(ValueError) as exc_info:
            validator.validate(args)  # type: ignore[union-attr]

        error_message = str(exc_info.value)
        assert "single-user-mode" in error_message.lower()
        assert "multi-user-mode" in error_message.lower()
        assert (
            "cannot specify both" in error_message.lower()
            or "mutually exclusive" in error_message.lower()
        )

    def test_error_message_is_clear_and_actionable(
        self, validator: object, args: argparse.Namespace
    ) -> None:
        """Error message provides clear guidance on how to fix the issue."""
        args.single_user_mode = True
        args.multi_user_mode = True

        with pytest.raises(ValueError) as exc_info:
            validator.validate(args)  # type: ignore[union-attr]

        error_message = str(exc_info.value)
        # Error message should reference the flags
        assert (
            "--single-user-mode" in error_message or "single-user-mode" in error_message
        )
        assert (
            "--multi-user-mode" in error_message or "multi-user-mode" in error_message
        )


# =============================================================================
# Backward Compatibility Tests
# =============================================================================
