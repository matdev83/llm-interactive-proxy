"""Model Registry Applicator - Extracts and applies model registry and limit enforcement CLI arguments.

This applicator handles:
- model_registry_download_enabled
- model_registry_url
- model_registry_update_interval_seconds
- model_limit_enforcement_enabled
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.parameter_resolution import ParameterSource


class ModelRegistryApplicator:
    """Applies model registry and limit enforcement CLI arguments to configuration."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply model registry-related CLI arguments to configuration overrides.

        Args:
            args: Parsed command-line arguments namespace
            overrides: Dictionary to collect configuration overrides
            resolution: Parameter resolution tracker for recording sources
        """
        # Model Registry settings
        if "model_registry" not in overrides:
            overrides["model_registry"] = {}

        registry_overrides = overrides["model_registry"]

        # Download enabled
        download_enabled = getattr(args, "model_registry_download_enabled", None)
        if download_enabled is not None:
            registry_overrides["download_enabled"] = download_enabled
            resolution.record(
                "model_registry.download_enabled",
                download_enabled,
                ParameterSource.CLI,
                origin="cli_args",
            )

        # URL
        url = getattr(args, "model_registry_url", None)
        if url is not None:
            registry_overrides["url"] = url
            resolution.record(
                "model_registry.url",
                url,
                ParameterSource.CLI,
                origin="cli_args",
            )

        # Update interval
        interval = getattr(args, "model_registry_update_interval_seconds", None)
        if interval is not None:
            registry_overrides["update_interval_seconds"] = interval
            resolution.record(
                "model_registry.update_interval_seconds",
                interval,
                ParameterSource.CLI,
                origin="cli_args",
            )

        # Model Limit Enforcement settings
        if "model_limit_enforcement" not in overrides:
            overrides["model_limit_enforcement"] = {}

        enforcement_overrides = overrides["model_limit_enforcement"]

        # Enforcement enabled
        enforcement_enabled = getattr(args, "model_limit_enforcement_enabled", None)
        if enforcement_enabled is not None:
            enforcement_overrides["enabled"] = enforcement_enabled
            resolution.record(
                "model_limit_enforcement.enabled",
                enforcement_enabled,
                ParameterSource.CLI,
                origin="cli_args",
            )
