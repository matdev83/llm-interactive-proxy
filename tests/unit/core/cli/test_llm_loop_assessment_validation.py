"""
Test cases for LLM loop assessment validation in CLI.

This module tests the validation that ensures both backend and model are provided
when --enable-llm-loop-assessment is used, and that the backend is valid.
"""

import pytest
from src.core.cli import parse_cli_args


class TestLLMLoopAssessmentValidation:
    """Test LLM loop assessment validation in CLI."""

    def test_assessment_disabled_passes_validation(self):
        """Test that disabled assessment passes validation without backend/model."""
        args = parse_cli_args(["--disable-llm-loop-assessment"])
        assert args.llm_loop_assessment_enabled is False

    def test_no_assessment_flag_passes_validation(self):
        """Test that no assessment flag passes validation."""
        args = parse_cli_args([])
        assert args.llm_loop_assessment_enabled is None

    def test_assessment_enabled_with_valid_model_passes(self):
        """Test that enabled assessment with a valid BACKEND:MODEL passes."""
        args = parse_cli_args(
            [
                "--enable-llm-loop-assessment",
                "--llm-assessment-model",
                "openai:gpt-4o-mini",
            ]
        )
        assert args.llm_loop_assessment_enabled is True
        assert args.llm_assessment_model == "openai:gpt-4o-mini"

    def test_assessment_enabled_with_another_valid_model_passes(self):
        """Test that enabled assessment with another valid BACKEND:MODEL passes."""
        args = parse_cli_args(
            [
                "--enable-llm-loop-assessment",
                "--llm-assessment-model",
                "anthropic:claude-3-haiku-20240307",
            ]
        )
        assert args.llm_loop_assessment_enabled is True
        assert args.llm_assessment_model == "anthropic:claude-3-haiku-20240307"

    def test_assessment_enabled_without_model_fails(self):
        """Test that enabled assessment without a model fails validation."""
        with pytest.raises(ValueError) as exc_info:
            parse_cli_args(["--enable-llm-loop-assessment"])

        error_msg = str(exc_info.value)
        assert "LLM assessment model must be specified" in error_msg
        assert "--llm-assessment-model BACKEND:MODEL" in error_msg

    def test_assessment_enabled_with_invalid_format_fails(self):
        """Test that enabled assessment with an invalid format fails validation."""
        with pytest.raises(ValueError) as exc_info:
            parse_cli_args(
                [
                    "--enable-llm-loop-assessment",
                    "--llm-assessment-model",
                    "openaigpt-4o-mini",
                ]
            )

        error_msg = str(exc_info.value)
        assert "Invalid format for --llm-assessment-model" in error_msg
        assert "Expected BACKEND:MODEL" in error_msg

    def test_assessment_enabled_with_empty_backend_fails(self):
        """Test that enabled assessment with an empty backend fails validation."""
        with pytest.raises(ValueError) as exc_info:
            parse_cli_args(
                [
                    "--enable-llm-loop-assessment",
                    "--llm-assessment-model",
                    ":gpt-4o-mini",
                ]
            )

        error_msg = str(exc_info.value)
        assert "Both backend and model must be specified" in error_msg

    def test_assessment_enabled_with_empty_model_fails(self):
        """Test that enabled assessment with an empty model fails validation."""
        with pytest.raises(ValueError) as exc_info:
            parse_cli_args(
                ["--enable-llm-loop-assessment", "--llm-assessment-model", "openai:"]
            )

        error_msg = str(exc_info.value)
        assert "Both backend and model must be specified" in error_msg

    def test_assessment_enabled_with_whitespace_backend_fails(self):
        """Test that enabled assessment with a whitespace-only backend fails validation."""
        with pytest.raises(ValueError) as exc_info:
            parse_cli_args(
                [
                    "--enable-llm-loop-assessment",
                    "--llm-assessment-model",
                    " :gpt-4o-mini",
                ]
            )

        error_msg = str(exc_info.value)
        assert "Both backend and model must be specified" in error_msg

    def test_assessment_enabled_with_whitespace_model_fails(self):
        """Test that enabled assessment with a whitespace-only model fails validation."""
        with pytest.raises(ValueError) as exc_info:
            parse_cli_args(
                ["--enable-llm-loop-assessment", "--llm-assessment-model", "openai: "]
            )

        error_msg = str(exc_info.value)
        assert "Both backend and model must be specified" in error_msg

    def test_assessment_enabled_with_invalid_backend_fails(self):
        """Test that enabled assessment with an invalid backend fails validation."""
        with pytest.raises(ValueError) as exc_info:
            parse_cli_args(
                [
                    "--enable-llm-loop-assessment",
                    "--llm-assessment-model",
                    "nonexistent-backend:some-model",
                ]
            )

        error_msg = str(exc_info.value)
        assert "Invalid backend 'nonexistent-backend' specified" in error_msg
        assert "Available backends:" in error_msg
        assert "openai" in error_msg
        assert "anthropic" in error_msg

    def test_assessment_enabled_with_old_backend_name_fails(self):
        """Test that enabled assessment with an old backend name fails validation."""
        with pytest.raises(ValueError) as exc_info:
            parse_cli_args(
                [
                    "--enable-llm-loop-assessment",
                    "--llm-assessment-model",
                    "gemini-cli-oauth-personal:gemini-2.5-pro",
                ]
            )

        error_msg = str(exc_info.value)
        assert "Invalid backend 'gemini-cli-oauth-personal' specified" in error_msg
        assert "gemini-oauth-plan" in error_msg
        assert "gemini-oauth-free" in error_msg

    def test_error_message_format_and_content(self):
        """Test that error messages have the proper format and helpful content."""
        with pytest.raises(ValueError) as exc_info:
            parse_cli_args(
                [
                    "--enable-llm-loop-assessment",
                    "--llm-assessment-model",
                    "invalid-backend:some-model",
                ]
            )

        error_msg = str(exc_info.value)
        lines = error_msg.split("\n")

        assert len(lines) >= 3
        assert "Invalid backend 'invalid-backend' specified" in lines[0]
        assert lines[1].startswith("Available backends:")
        assert lines[2].startswith("Use a valid backend")

    def test_available_backends_list_contains_expected_backends(self):
        """Test that the available backends list contains expected registered backends."""
        with pytest.raises(ValueError) as exc_info:
            parse_cli_args(
                [
                    "--enable-llm-loop-assessment",
                    "--llm-assessment-model",
                    "invalid:model",
                ]
            )

        error_msg = str(exc_info.value)

        expected_backends = [
            "openai",
            "anthropic",
            "gemini",
            "gemini-oauth-plan",
            "gemini-oauth-free",
            "openrouter",
        ]

        for backend in expected_backends:
            assert (
                backend in error_msg
            ), f"Expected backend '{backend}' not found in error message"

    def test_assessment_enabled_without_model_fails_first(self):
        """Test that when the model is missing, the validation fails."""
        with pytest.raises(ValueError) as exc_info:
            parse_cli_args(["--enable-llm-loop-assessment"])

        error_msg = str(exc_info.value)
        assert "LLM assessment model must be specified" in error_msg

    def test_validation_only_runs_when_assessment_enabled(self):
        """Test that validation only runs when assessment is explicitly enabled."""
        parse_cli_args(
            ["--llm-assessment-model", "openai:gpt-4"]
        )  # No error without --enable

        # Validation should run only when explicitly enabled
        with pytest.raises(ValueError):
            parse_cli_args(
                [
                    "--enable-llm-loop-assessment",
                    "--llm-assessment-model",
                    "invalid-backend:some-model",
                ]
            )
