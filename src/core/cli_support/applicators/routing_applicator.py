"""Routing Applicator - Extracts and applies routing CLI arguments.

This applicator handles:
- disable_routing_with_backend_ids
- disable_routing_with_backend_names
- disable_routing_with_only_model_names

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


class RoutingApplicator:
    """Applies routing CLI arguments to configuration."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply routing CLI arguments to configuration overrides."""
        routing_overrides: dict[str, Any] = {}

        if getattr(args, "disable_routing_with_backend_ids", None) is not None:
            routing_overrides["disable_backend_ids"] = (
                args.disable_routing_with_backend_ids
            )
            resolution.record(
                "routing.disable_backend_ids",
                args.disable_routing_with_backend_ids,
                ParameterSource.CLI,
                origin="--disable-routing-with-backend-ids",
            )

        if getattr(args, "disable_routing_with_backend_names", None) is not None:
            routing_overrides["disable_backend_names"] = (
                args.disable_routing_with_backend_names
            )
            resolution.record(
                "routing.disable_backend_names",
                args.disable_routing_with_backend_names,
                ParameterSource.CLI,
                origin="--disable-routing-with-backend-names",
            )

        if getattr(args, "disable_routing_with_only_model_names", None) is not None:
            routing_overrides["disable_model_names"] = (
                args.disable_routing_with_only_model_names
            )
            resolution.record(
                "routing.disable_model_names",
                args.disable_routing_with_only_model_names,
                ParameterSource.CLI,
                origin="--disable-routing-with-only-model-names",
            )

        if routing_overrides:
            overrides["routing"] = routing_overrides
