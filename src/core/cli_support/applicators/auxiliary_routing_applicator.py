"""Auxiliary Routing Applicator - Extracts and applies auxiliary routing CLI arguments.

This applicator handles:
- auxiliary_routing_enabled
- auxiliary_routing_backend
- auxiliary_routing_model
- auxiliary_routing_max_messages
- disable_default_openrouter_auxiliary_routing

Requirements satisfied:
- 6.1: ConfigurationApplicator delegates to domain-specific applicators
- 6.2: Each domain applicator only modifies its relevant configuration section
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.cli_support.protocols import CliArgs, CliOverrides
    from src.core.config.parameter_resolution import ParameterResolution

from src.core.config.models.access_mode import AccessMode
from src.core.config.parameter_resolution import ParameterSource
from src.core.domain.model_utils import (
    has_explicit_backend_selector,
    parse_model_backend,
)

# Default auxiliary model to use when OpenRouter API key is detected
_DEFAULT_OPENROUTER_AUXILIARY_MODEL = "openrouter/free"
_DEFAULT_OPENROUTER_AUXILIARY_BACKEND = "openrouter"


def _has_openrouter_api_key() -> bool:
    """Check if any OpenRouter API key environment variable is set.

    Checks for OPENROUTER_API_KEY and numbered variants like OPENROUTER_API_KEY_1, etc.

    Returns:
        True if any OPENROUTER_API_KEY* environment variable is set and non-empty.
    """
    # Check base OPENROUTER_API_KEY
    if os.getenv("OPENROUTER_API_KEY"):
        return True

    # Check for numbered variants (OPENROUTER_API_KEY_1, OPENROUTER_API_KEY_2, etc.)
    pattern = re.compile(r"^OPENROUTER_API_KEY_\d+$")
    return any(pattern.match(key) and os.environ[key] for key in os.environ)


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
            if has_explicit_backend_selector(model_val):
                parsed = parse_model_backend(model_val, "")
                backend = parsed.backend_type.strip()
                model = parsed.model_name.strip()
                if backend and model:
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

        disable_cli = getattr(args, "disable_auxiliary_routing", None)
        disable_from_base = getattr(
            args, "auxiliary_routing_disabled_from_base_config", False
        )

        is_disabled = (
            bool(disable_cli) if disable_cli is not None else disable_from_base
        )

        self._try_auto_enable(
            aux_routing_overrides,
            overrides,
            resolution,
            is_disabled=is_disabled,
            args=args,
        )

        # Handle disable default OpenRouter flag
        disable_default_openrouter = getattr(
            args, "disable_default_openrouter_auxiliary_routing", None
        )
        if disable_default_openrouter is not None:
            aux_routing_overrides["disable_default_openrouter"] = (
                disable_default_openrouter
            )
            resolution.record(
                "auxiliary_routing.disable_default_openrouter",
                disable_default_openrouter,
                ParameterSource.CLI,
                origin="--disable-default-open-router-auxiliary-routing",
            )

        # Auto-detect OpenRouter API key and apply default auxiliary model
        # This happens when:
        # 1. Auxiliary routing is being enabled (or already enabled in base config)
        # 2. No model is explicitly configured
        # 3. OpenRouter API key is detected in environment
        # 4. The disable-default-openrouter flag is not set
        self._apply_default_openrouter_model_if_needed(
            aux_routing_overrides, resolution
        )

        if aux_routing_overrides:
            overrides["auxiliary_routing"] = aux_routing_overrides

    def _try_auto_enable(
        self,
        aux_routing_overrides: dict[str, Any],
        overrides: CliOverrides,
        resolution: ParameterResolution,
        *,
        is_disabled: bool,
        args: CliArgs,
    ) -> None:
        """Auto-enable auxiliary routing in single user mode with OpenRouter API key.

        Auto-enable is triggered when ALL conditions are met:
        1. `--disable-auxiliary-routing` is NOT set
        2. `auxiliary_routing.disable` is NOT set in base config
        3. Access mode is SINGLE_USER
        4. OPENROUTER_API_KEY is detected in environment
        5. `--enable-auxiliary-routing` was NOT explicitly provided (None)

        If auto-enable fires, `enabled` and default `backend`/`model` are set.
        Explicitly provided `--auxiliary-routing-model` is preserved.
        """
        if is_disabled:
            return

        already_explicitly_enabled = (
            getattr(args, "auxiliary_routing_enabled", None) is not None
        )
        if already_explicitly_enabled:
            return

        if not _has_openrouter_api_key():
            return

        access_mode = None
        override_access_mode = overrides.get("access_mode")
        if isinstance(override_access_mode, dict):
            access_mode = override_access_mode.get("mode")
        elif isinstance(override_access_mode, AccessMode):
            access_mode = override_access_mode

        if access_mode is None:
            access_mode = AccessMode.SINGLE_USER

        if access_mode != AccessMode.SINGLE_USER:
            return

        aux_routing_overrides["enabled"] = True
        resolution.record(
            "auxiliary_routing.enabled",
            True,
            ParameterSource.DEFAULT,
            origin="auto-enable (single user mode + OPENROUTER_API_KEY)",
        )

        already_has_model = "model" in aux_routing_overrides
        already_has_backend = "backend" in aux_routing_overrides
        if already_has_model or already_has_backend:
            return

        aux_routing_overrides["backend"] = _DEFAULT_OPENROUTER_AUXILIARY_BACKEND
        aux_routing_overrides["model"] = _DEFAULT_OPENROUTER_AUXILIARY_MODEL

        resolution.record(
            "auxiliary_routing.backend",
            _DEFAULT_OPENROUTER_AUXILIARY_BACKEND,
            ParameterSource.DEFAULT,
            origin="auto-enable OpenRouter default",
        )
        resolution.record(
            "auxiliary_routing.model",
            _DEFAULT_OPENROUTER_AUXILIARY_MODEL,
            ParameterSource.DEFAULT,
            origin="auto-enable OpenRouter default",
        )

    def _apply_default_openrouter_model_if_needed(
        self,
        aux_routing_overrides: dict[str, Any],
        resolution: ParameterResolution,
    ) -> None:
        """Apply default OpenRouter model if conditions are met.

        Conditions:
        1. Auxiliary routing is enabled (or being enabled via CLI)
        2. No model/backend is explicitly configured
        3. OpenRouter API key is detected in environment
        4. disable_default_openrouter is not set
        """
        # Check if auxiliary routing is enabled
        is_enabled = aux_routing_overrides.get("enabled", False)
        if not is_enabled:
            return

        # Check if disable flag is set
        if aux_routing_overrides.get("disable_default_openrouter", False):
            return

        # Check if model or backend is already explicitly configured
        has_explicit_model = "model" in aux_routing_overrides
        has_explicit_backend = "backend" in aux_routing_overrides
        if has_explicit_model or has_explicit_backend:
            return

        # Check if OpenRouter API key is present
        if not _has_openrouter_api_key():
            return

        # Apply default OpenRouter auxiliary model
        aux_routing_overrides["backend"] = _DEFAULT_OPENROUTER_AUXILIARY_BACKEND
        aux_routing_overrides["model"] = _DEFAULT_OPENROUTER_AUXILIARY_MODEL

        resolution.record(
            "auxiliary_routing.backend",
            _DEFAULT_OPENROUTER_AUXILIARY_BACKEND,
            ParameterSource.DEFAULT,
            origin="OPENROUTER_API_KEY auto-detection",
        )
        resolution.record(
            "auxiliary_routing.model",
            _DEFAULT_OPENROUTER_AUXILIARY_MODEL,
            ParameterSource.DEFAULT,
            origin="OPENROUTER_API_KEY auto-detection",
        )
