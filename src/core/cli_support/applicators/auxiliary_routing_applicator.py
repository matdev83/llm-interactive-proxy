"""Auxiliary Routing Applicator - Extracts and applies auxiliary routing CLI arguments.

This applicator handles:
- auxiliary_routing_enabled
- auxiliary_routing_backend
- auxiliary_routing_model
- auxiliary_routing_max_messages

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


class AuxiliaryRoutingApplicator:
    """Applies auxiliary routing CLI arguments to configuration."""

    def apply(
        self,
        args: CliArgs,
        overrides: CliOverrides,
        resolution: ParameterResolution,
    ) -> None:
        """Apply auxiliary routing CLI arguments to configuration overrides."""
        aux_routing_overrides: dict[str, Any] = {}

        if getattr(args, "auxiliary_routing_enabled", None) is not None:
            aux_routing_overrides["enabled"] = args.auxiliary_routing_enabled
            resolution.record(
                "auxiliary_routing.enabled",
                args.auxiliary_routing_enabled,
                ParameterSource.CLI,
                origin="--enable-auxiliary-routing",
            )

        if getattr(args, "auxiliary_routing_backend", None) is not None:
            aux_routing_overrides["backend"] = args.auxiliary_routing_backend
            resolution.record(
                "auxiliary_routing.backend",
                args.auxiliary_routing_backend,
                ParameterSource.CLI,
                origin="--auxiliary-routing-backend",
            )

        if getattr(args, "auxiliary_routing_model", None) is not None:

            model_val: str = args.auxiliary_routing_model
            if ":" in model_val:
                backend, model = model_val.split(":", 1)
                aux_routing_overrides["backend"] = backend
                aux_routing_overrides["model"] = model

                resolution.record(
                    "auxiliary_routing.backend",
                    backend,
                    ParameterSource.CLI,
                    origin="--auxiliary-routing-model (parsed)",
                )
                resolution.record(
                    "auxiliary_routing.model",
                    model,
                    ParameterSource.CLI,
                    origin="--auxiliary-routing-model (parsed)",
                )
            else:
                aux_routing_overrides["model"] = model_val
                resolution.record(
                    "auxiliary_routing.model",
                    model_val,
                    ParameterSource.CLI,
                    origin="--auxiliary-routing-model",
                )

        if getattr(args, "auxiliary_routing_max_messages", None) is not None:
            aux_routing_overrides["max_message_count"] = (
                args.auxiliary_routing_max_messages
            )
            resolution.record(
                "auxiliary_routing.max_message_count",
                args.auxiliary_routing_max_messages,
                ParameterSource.CLI,
                origin="--auxiliary-routing-max-messages",
            )

        if aux_routing_overrides:
            overrides["auxiliary_routing"] = aux_routing_overrides
