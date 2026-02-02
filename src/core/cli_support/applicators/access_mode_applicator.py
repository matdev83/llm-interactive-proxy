"""Access Mode Applicator - Extracts and applies access mode CLI arguments.

This applicator handles:
- single_user_mode: Run in Single User Mode (default)
- multi_user_mode: Run in Multi User Mode

Requirements satisfied:
- 1.1: Defaults to Single User Mode when no flag specified
- 1.2: CLI flag --single-user-mode sets mode to SINGLE_USER
- 1.3: CLI flag --multi-user-mode sets mode to MULTI_USER
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.models.access_mode import AccessMode
from src.core.config.parameter_resolution import ParameterSource


class AccessModeApplicator:
    """Applies access mode CLI arguments to configuration.

    Handles:
    - single_user_mode: Enable Single User Mode via --single-user-mode flag
    - multi_user_mode: Enable Multi User Mode via --multi-user-mode flag
    - Default: Single User Mode when no flag is specified
    """

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply access mode CLI arguments to configuration overrides.

        Args:
            args: Parsed command-line arguments namespace
            overrides: Dictionary to collect configuration overrides
            resolution: Parameter resolution tracker for recording sources
        """
        single_user_mode = getattr(args, "single_user_mode", False)
        multi_user_mode = getattr(args, "multi_user_mode", False)

        # Determine access mode from CLI flags
        if single_user_mode:
            mode = AccessMode.SINGLE_USER
            flag_name = "--single-user-mode"
            source = ParameterSource.CLI
        elif multi_user_mode:
            mode = AccessMode.MULTI_USER
            flag_name = "--multi-user-mode"
            source = ParameterSource.CLI
        else:
            # Default to Single User Mode when no flag specified (requirement 1.1)
            mode = AccessMode.SINGLE_USER
            flag_name = "default"
            source = ParameterSource.DEFAULT

        # Apply to overrides
        overrides["access_mode"] = {"mode": mode}

        # Record parameter resolution
        resolution.record(
            "access_mode.mode",
            mode,
            source,
            origin=flag_name,
        )
