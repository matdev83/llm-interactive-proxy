"""Sandboxing Applicator - Extracts and applies sandboxing CLI arguments.

This applicator handles:
- enable_sandboxing

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


class SandboxingApplicator:
    """Applies sandboxing CLI arguments to configuration."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply sandboxing CLI arguments to configuration overrides."""
        sandboxing_overrides: dict[str, Any] = {}

        if getattr(args, "enable_sandboxing", None) is not None:
            sandboxing_overrides["enabled"] = args.enable_sandboxing
            os.environ["ENABLE_SANDBOXING"] = (
                "true" if args.enable_sandboxing else "false"
            )
            resolution.record(
                "sandboxing.enabled",
                args.enable_sandboxing,
                ParameterSource.CLI,
                origin="--enable-sandboxing",
            )

        if sandboxing_overrides:
            overrides["sandboxing"] = sandboxing_overrides
