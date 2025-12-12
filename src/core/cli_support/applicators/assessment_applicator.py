"""Assessment Applicator - Extracts and applies LLM assessment CLI arguments.

This applicator handles:
- llm_assessment_enabled, llm_assessment_turn_threshold
- llm_assessment_confidence_threshold, llm_assessment_model
- llm_assessment_history_window

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource


class AssessmentApplicator:
    """Applies LLM assessment CLI arguments to configuration.

    Handles:
    - LLM loop assessment settings
    """

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply assessment-related CLI arguments to configuration overrides."""
        assessment_overrides: dict[str, Any] = {}

        if getattr(args, "llm_assessment_enabled", None) is not None:
            assessment_overrides["enabled"] = args.llm_assessment_enabled
            resolution.record(
                "assessment.enabled",
                args.llm_assessment_enabled,
                ParameterSource.CLI,
                origin="--enable-llm-assessment",
            )

        if getattr(args, "llm_assessment_turn_threshold", None) is not None:
            assessment_overrides["turn_threshold"] = args.llm_assessment_turn_threshold
            resolution.record(
                "assessment.turn_threshold",
                args.llm_assessment_turn_threshold,
                ParameterSource.CLI,
                origin="--llm-assessment-turn-threshold",
            )

        if getattr(args, "llm_assessment_confidence_threshold", None) is not None:
            assessment_overrides["confidence_threshold"] = (
                args.llm_assessment_confidence_threshold
            )
            resolution.record(
                "assessment.confidence_threshold",
                args.llm_assessment_confidence_threshold,
                ParameterSource.CLI,
                origin="--llm-assessment-confidence-threshold",
            )

        if getattr(args, "llm_assessment_model", None) is not None:
            model_str = args.llm_assessment_model
            backend, model = model_str.split(":", 1)
            assessment_overrides["backend"] = backend
            assessment_overrides["model"] = model
            resolution.record(
                "assessment.backend",
                backend,
                ParameterSource.CLI,
                origin="--llm-assessment-model",
            )
            resolution.record(
                "assessment.model",
                model,
                ParameterSource.CLI,
                origin="--llm-assessment-model",
            )

        if getattr(args, "llm_assessment_history_window", None) is not None:
            assessment_overrides["history_window"] = args.llm_assessment_history_window
            resolution.record(
                "assessment.history_window",
                args.llm_assessment_history_window,
                ParameterSource.CLI,
                origin="--llm-assessment-history-window",
            )

        if assessment_overrides:
            overrides["assessment"] = assessment_overrides
