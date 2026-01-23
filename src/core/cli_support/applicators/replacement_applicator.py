"""Replacement Applicator - Extracts and applies random model replacement CLI arguments.

This applicator handles:
- replacement_enabled
- replacement_probability
- replacement_backend_model
- replacement_turn_count

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource


class ReplacementApplicator:
    """Applies random model replacement CLI arguments to configuration."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply random model replacement CLI arguments to configuration overrides."""
        replacement_overrides: dict[str, Any] = {}

        if getattr(args, "replacement_enabled", None) is not None:
            replacement_overrides["enabled"] = args.replacement_enabled
            os.environ["REPLACEMENT_ENABLED"] = (
                "true" if args.replacement_enabled else "false"
            )
            resolution.record(
                "replacement.enabled",
                args.replacement_enabled,
                ParameterSource.CLI,
                origin="--enable-replacement",
            )

        if getattr(args, "replacement_probability", None) is not None:
            replacement_overrides["probability"] = args.replacement_probability
            os.environ["REPLACEMENT_PROBABILITY"] = str(args.replacement_probability)
            resolution.record(
                "replacement.probability",
                args.replacement_probability,
                ParameterSource.CLI,
                origin="--replacement-probability",
            )

        if getattr(args, "replacement_backend_model", None) is not None:
            replacement_overrides["backend_model"] = args.replacement_backend_model
            os.environ["REPLACEMENT_BACKEND_MODEL"] = args.replacement_backend_model
            resolution.record(
                "replacement.backend_model",
                args.replacement_backend_model,
                ParameterSource.CLI,
                origin="--replacement-backend-model",
            )

        if getattr(args, "replacement_turn_count", None) is not None:
            replacement_overrides["turn_count"] = args.replacement_turn_count
            os.environ["REPLACEMENT_TURN_COUNT"] = str(args.replacement_turn_count)
            resolution.record(
                "replacement.turn_count",
                args.replacement_turn_count,
                ParameterSource.CLI,
                origin="--replacement-turn-count",
            )

        if replacement_overrides:
            overrides["replacement"] = replacement_overrides
