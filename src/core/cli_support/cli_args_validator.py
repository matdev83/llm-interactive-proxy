"""CliArgsValidator for non-argparse CLI validation.

This module provides the CliArgsValidator class which performs validation on
parsed CLI arguments beyond what argparse provides. This includes cross-field
validation, format validation, and backend registry checks.

Requirements satisfied:
- 1.4: Structured, testable errors from validation service
- 7.5: Stable exception messages for backward compatibility
"""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from src.core.services.backend_registry import backend_registry

if TYPE_CHECKING:
    pass


class CliArgsValidator:
    """Validates parsed CLI arguments beyond argparse's built-in checks.

    This class performs non-argparse validation on already-parsed arguments,
    such as validating LLM loop assessment configuration. It raises stable,
    testable exceptions on validation failure.

    Usage:
        validator = CliArgsValidator()
        validator.validate(args)  # Raises ValueError if invalid
    """

    def validate(self, args: argparse.Namespace) -> None:
        """Validate parsed CLI arguments.

        Args:
            args: Parsed CLI arguments namespace

        Raises:
            ValueError: If validation fails, with detailed error message
        """
        self._validate_llm_assessment_config(args)
        self._validate_replacement_config(args)

    def _validate_llm_assessment_config(self, args: argparse.Namespace) -> None:

        """Validate LLM assessment configuration.

        Raises:
            ValueError: If assessment is enabled but the model is missing or invalid.
        """
        # Check if assessment is enabled
        assessment_enabled = getattr(args, "llm_assessment_enabled", None)
        if not assessment_enabled:
            return

        # Get the consolidated model string
        model_str = getattr(args, "llm_assessment_model", None)

        # The model must be provided when assessment is enabled
        if not model_str or not model_str.strip():
            raise ValueError(
                "LLM assessment model must be specified when --enable-llm-assessment is used.\n"
                "Use --llm-assessment-model BACKEND:MODEL\n"
                "Example: --llm-assessment-model openai:gpt-4o-mini"
            )

        # Validate the format
        if ":" not in model_str:
            raise ValueError(
                "Invalid format for --llm-assessment-model. Expected BACKEND:MODEL.\n"
                "Example: --llm-assessment-model openai:gpt-4o-mini"
            )

        backend, model = model_str.split(":", 1)
        backend = backend.strip()
        model = model.strip()
        if not backend or not model:
            raise ValueError(
                "Invalid format for --llm-assessment-model. Both backend and model must be specified.\n"
                "Example: --llm-assessment-model openai:gpt-4o-mini"
            )

        # Validate backend exists
        registered_backends = backend_registry.get_registered_backends()
        if backend not in registered_backends:
            available_backends = ", ".join(sorted(registered_backends))
            raise ValueError(
                f"Invalid backend '{backend}' specified for LLM assessment.\n"
                f"Available backends: {available_backends}\n"
                f"Use a valid backend in the format BACKEND:MODEL."
            )

    def _validate_replacement_config(self, args: argparse.Namespace) -> None:
        """Validate random model replacement configuration."""
        if not getattr(args, "replacement_enabled", False):
            return

        model_str = getattr(args, "replacement_backend_model", None)
        if not model_str:
            raise ValueError(
                "Replacement backend:model must be specified when --enable-replacement is used.\n"
                "Use --replacement-backend-model BACKEND:MODEL"
            )

        if ":" not in model_str:
            raise ValueError(
                f"Invalid format for --replacement-backend-model: '{model_str}'. "
                "Expected BACKEND:MODEL."
            )

        backend, model = model_str.split(":", 1)
        if not backend or not model:
            raise ValueError(
                f"Invalid format for --replacement-backend-model: '{model_str}'. "
                "Both backend and model must be specified."
            )

        registered_backends = backend_registry.get_registered_backends()
        if backend not in registered_backends:
            available_backends = ", ".join(sorted(registered_backends))
            raise ValueError(
                f"Invalid backend '{backend}' specified for model replacement.\n"
                f"Available backends: {available_backends}"
            )

        prob = getattr(args, "replacement_probability", None)
        if prob is not None and not (0.0 <= prob <= 1.0):
            raise ValueError(
                f"Invalid --replacement-probability: {prob}. Must be between 0.0 and 1.0."
            )

        turn_count = getattr(args, "replacement_turn_count", None)
        if turn_count is not None and turn_count < 1:
            raise ValueError(
                f"Invalid --replacement-turn-count: {turn_count}. Must be at least 1."
            )

