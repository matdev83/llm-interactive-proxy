"""Edit Precision Applicator - Extracts and applies edit precision CLI arguments.

This applicator handles:
- edit_precision_enabled, edit_precision_temperature
- edit_precision_min_top_p, edit_precision_override_top_p
- edit_precision_override_top_k, edit_precision_target_top_k
- edit_precision_exclude_agents_regex

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


class EditPrecisionApplicator:
    """Applies edit precision CLI arguments to configuration."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply edit precision CLI arguments to configuration overrides."""
        edit_precision_overrides: dict[str, Any] = {}

        if getattr(args, "edit_precision_enabled", None) is not None:
            edit_precision_overrides["enabled"] = args.edit_precision_enabled
            resolution.record(
                "edit_precision.enabled",
                args.edit_precision_enabled,
                ParameterSource.CLI,
                origin="--enable/disable-edit-precision",
            )

        if getattr(args, "edit_precision_temperature", None) is not None:
            edit_precision_overrides["temperature"] = max(
                0.0, args.edit_precision_temperature
            )
            resolution.record(
                "edit_precision.temperature",
                edit_precision_overrides["temperature"],
                ParameterSource.CLI,
                origin="--edit-precision-temperature",
            )

        if getattr(args, "edit_precision_min_top_p", None) is not None:
            edit_precision_overrides["min_top_p"] = max(
                0.0, args.edit_precision_min_top_p
            )
            resolution.record(
                "edit_precision.min_top_p",
                edit_precision_overrides["min_top_p"],
                ParameterSource.CLI,
                origin="--edit-precision-min-top-p",
            )

        if getattr(args, "edit_precision_override_top_p", None) is not None:
            edit_precision_overrides["override_top_p"] = (
                args.edit_precision_override_top_p
            )
            resolution.record(
                "edit_precision.override_top_p",
                edit_precision_overrides["override_top_p"],
                ParameterSource.CLI,
                origin="--edit-precision-override-top-p",
            )

        if getattr(args, "edit_precision_override_top_k", None) is not None:
            edit_precision_overrides["override_top_k"] = (
                args.edit_precision_override_top_k
            )
            resolution.record(
                "edit_precision.override_top_k",
                edit_precision_overrides["override_top_k"],
                ParameterSource.CLI,
                origin="--edit-precision-override-top-k",
            )

        if getattr(args, "edit_precision_target_top_k", None) is not None:
            target_value = (
                args.edit_precision_target_top_k
                if args.edit_precision_target_top_k > 0
                else None
            )
            edit_precision_overrides["target_top_k"] = target_value
            resolution.record(
                "edit_precision.target_top_k",
                target_value,
                ParameterSource.CLI,
                origin="--edit-precision-target-top-k",
            )

        if getattr(args, "edit_precision_exclude_agents_regex", None) is not None:
            edit_precision_overrides["exclude_agents_regex"] = (
                args.edit_precision_exclude_agents_regex
            )
            resolution.record(
                "edit_precision.exclude_agents_regex",
                edit_precision_overrides["exclude_agents_regex"],
                ParameterSource.CLI,
                origin="--edit-precision-exclude-agents",
            )

        if edit_precision_overrides:
            overrides["edit_precision"] = edit_precision_overrides
