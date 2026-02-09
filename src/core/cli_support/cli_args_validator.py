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
        self._validate_access_mode_flags(args)
        self._validate_llm_assessment_config(args)
        self._validate_replacement_config(args)

    def _validate_access_mode_flags(self, args: argparse.Namespace) -> None:
        """Validate access mode flags.

        Ensures that --single-user-mode and --multi-user-mode are not both specified.

        Raises:
            ValueError: If both access mode flags are specified.
        """
        single_user_mode = getattr(args, "single_user_mode", False)
        multi_user_mode = getattr(args, "multi_user_mode", False)

        if single_user_mode and multi_user_mode:
            raise ValueError(
                "Cannot specify both --single-user-mode and --multi-user-mode. Choose one."
            )

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

        # Check for new replacement_rules format
        replacement_rules = getattr(args, "replacement_rules", None)
        if replacement_rules is not None:
            if not replacement_rules:
                raise ValueError(
                    "At least one replacement rule must be specified when --enable-replacement is used.\n"
                    "Use --random-model-replacement-from-to '<from>=<to>' (can be specified multiple times)"
                )

            # Check for wildcard exclusivity: if any rule has wildcard, it must be the only rule
            has_wildcard = any(
                rule_str.split("=", 1)[0].strip() == "*"
                for rule_str in replacement_rules
            )
            if has_wildcard and len(replacement_rules) > 1:
                raise ValueError(
                    "Invalid replacement rules configuration:\n"
                    "When using wildcard '*' as a source pattern, it must be the ONLY rule specified.\n"
                    "Wildcard matches all models, making other rules redundant or unreachable.\n"
                    "Either use only '--random-model-replacement-from-to \"*=backend:model\"' OR "
                    "use multiple specific rules without wildcards."
                )

            registered_backends = backend_registry.get_registered_backends()

            for i, rule_str in enumerate(replacement_rules):
                # Validate format (already validated by argparse, but double-check)
                if "=" not in rule_str:
                    raise ValueError(
                        f"Invalid replacement rule format at index {i}: '{rule_str}'. "
                        f"Expected '<from-model-name>=<to-model-name>'"
                    )

                parts = rule_str.split("=", 1)
                if len(parts) != 2:
                    raise ValueError(
                        f"Invalid replacement rule format at index {i}: '{rule_str}'. "
                        f"Expected exactly one '=' separator"
                    )

                from_pattern = parts[0].strip()
                to_part = parts[1].strip()

                if not from_pattern:
                    raise ValueError(
                        f"Invalid replacement rule at index {i}: '<from-model-name>' cannot be empty"
                    )

                if ":" not in to_part:
                    raise ValueError(
                        f"Invalid replacement rule at index {i}: '<to-model-name>' must be in format 'backend:model', got '{to_part}'"
                    )

                to_backend, to_model = to_part.split(":", 1)
                if not to_backend or not to_model:
                    raise ValueError(
                        f"Invalid replacement rule at index {i}: Both backend and model must be specified in <to-model-name>"
                    )

                # Validate that replacement target is not a wildcard
                if to_backend == "*" or to_model == "*":
                    raise ValueError(
                        f"Invalid replacement rule at index {i}: '{rule_str}'\n"
                        f"Replacement target cannot use wildcard '*'.\n"
                        f"Only the source pattern (left side) can be a wildcard."
                    )

                # Validate target backend exists
                if to_backend not in registered_backends:
                    available_backends = ", ".join(sorted(registered_backends))
                    raise ValueError(
                        f"Replacement rule at index {i}: Target backend '{to_backend}' is not registered. "
                        f"Available backends: {available_backends}"
                    )

                # Validate from_pattern formats
                if from_pattern != "*" and ":" in from_pattern:
                    # Fully qualified format: validate it has both parts
                    from_parts = from_pattern.split(":", 1)
                    if len(from_parts) != 2 or not from_parts[0] or not from_parts[1]:
                        raise ValueError(
                            f"Invalid replacement rule at index {i}: "
                            f"If <from-model-name> contains ':', it must be in format 'backend:model'"
                        )

        # Backward compatibility: validate old replacement_backend_model format
        model_str = getattr(args, "replacement_backend_model", None)
        if model_str:
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

        # If neither format is provided, raise error
        if not replacement_rules and not model_str:
            raise ValueError(
                "Replacement backend:model must be specified when --enable-replacement is used.\n"
                "Use --random-model-replacement-from-to '<from>=<to>' (can be specified multiple times)\n"
                "Or use --replacement-backend-model BACKEND:MODEL (deprecated)"
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
