"""Compaction Applicator - Extracts and applies context compaction CLI arguments.

This applicator handles:
- enable_context_compaction
- compaction_min_tokens

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


class CompactionApplicator:
    """Applies context compaction CLI arguments to configuration."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply compaction CLI arguments to configuration overrides."""
        compaction_overrides: dict[str, Any] = {}

        if getattr(args, "enable_context_compaction", None) is not None:
            compaction_overrides["enabled"] = args.enable_context_compaction
            resolution.record(
                "compaction.enabled",
                args.enable_context_compaction,
                ParameterSource.CLI,
                origin="--enable-context-compaction",
            )

        if getattr(args, "compaction_min_tokens", None) is not None:
            compaction_overrides["token_threshold"] = args.compaction_min_tokens
            resolution.record(
                "compaction.token_threshold",
                args.compaction_min_tokens,
                ParameterSource.CLI,
                origin="--compaction-min-tokens",
            )

        if compaction_overrides:
            overrides["compaction"] = compaction_overrides
