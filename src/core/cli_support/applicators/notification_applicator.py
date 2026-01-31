"""Notification Applicator - Extracts and applies notification-related CLI arguments.

This applicator handles:
- notifications_enabled: Enable/disable desktop notifications

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource


class NotificationApplicator:
    """Applies notification-related CLI arguments to configuration.

    Handles:
    - notifications_enabled: Enable/disable desktop notifications (CLI override)
    """

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply notification-related CLI arguments to configuration overrides.

        Args:
            args: Parsed command-line arguments namespace
            overrides: Dictionary to collect configuration overrides
            resolution: Parameter resolution tracker for recording sources
        """
        # CLI flag has highest priority
        notifications_enabled = getattr(args, "notifications_enabled", None)
        if notifications_enabled is not None:
            overrides["notifications"] = {"enabled": notifications_enabled}
            flag_name = (
                "--enable-notifications"
                if notifications_enabled
                else "--disable-notifications"
            )
            resolution.record(
                "notifications.enabled",
                notifications_enabled,
                ParameterSource.CLI,
                origin=flag_name,
            )
