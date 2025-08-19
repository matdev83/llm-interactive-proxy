import json
import logging
import os
from pathlib import Path
from typing import Any  # Added Optional and Tuple

from fastapi import FastAPI

from src.command_prefix import validate_command_prefix
from src.core.domain.model_utils import (
    ModelDefaults,  # Add import for model config classes
)

logger = logging.getLogger(__name__)


class ConfigManager:
    def __init__(self, app: FastAPI, path: str) -> None:
        self.app = app
        self.path = Path(path)

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text())
        except Exception as e:  # pragma: no cover - should rarely happen
            logger.warning("Failed to load config file %s: %s", self.path, e)
            return
        self.apply(data)

    def _apply_default_backend(self, backend_value: Any) -> None:
        if isinstance(backend_value, str):
            # Check if CLI argument was provided (LLM_BACKEND env var set)
            # If so, don't override it with config file value
            cli_backend = os.getenv("LLM_BACKEND")
            if cli_backend and cli_backend != backend_value:
                logger.info(
                    f"Skipping config file backend '{backend_value}' because CLI argument '{cli_backend}' takes precedence"
                )
                return

            if backend_value in self.app.state.functional_backends:
                self.app.state.backend_type = backend_value
                # Convert backend name to valid attribute name (replace hyphens with underscores)
                # Resolve backend via DI-backed BackendService if available
                if hasattr(self.app.state, "service_provider"):
                    try:
                        from src.core.interfaces.backend_service_interface import (
                            IBackendService,
                        )

                        backend_service = self.app.state.service_provider.get_required_service(
                            IBackendService
                        )
                        if backend_service and backend_value in getattr(backend_service, "_backends", {}):
                            self.app.state.backend = backend_service._backends[backend_value]
                            return
                    except Exception:
                        # If DI resolution fails, do not fall back to legacy state
                        pass
                # Do not use legacy app.state.<backend>_backend attributes; require DI
            else:
                raise ValueError(
                    f"Default backend '{backend_value}' is not in functional_backends."
                )

    def _apply_interactive_mode(self, mode_value: Any) -> None:
        if isinstance(mode_value, bool) and hasattr(self.app.state, "service_provider"):
            # Get session service from DI
            try:
                from src.core.interfaces.session_service_interface import (
                    ISessionService,
                )

                session_service = self.app.state.service_provider.get_required_service(
                    ISessionService
                )
                session_service.default_interactive_mode = mode_value
            except Exception as e:
                logger.warning(f"Failed to set interactive mode: {e}")

    def _apply_redact_api_keys(self, redact_value: Any) -> None:
        if isinstance(redact_value, bool):
            self.app.state.api_key_redaction_enabled = redact_value
            self.app.state.default_api_key_redaction_enabled = redact_value

    def _apply_command_prefix(self, prefix_value: Any) -> None:
        if isinstance(prefix_value, str):
            err = validate_command_prefix(prefix_value)
            if err:
                logger.warning(f"Invalid command prefix in config: {err}")
            else:
                self.app.state.command_prefix = prefix_value

    def _apply_model_defaults(self, model_defaults_value: Any) -> list[str]:
        """Apply model-specific default configurations."""
        warnings: list[str] = []
        if not isinstance(model_defaults_value, dict):
            return warnings

        # Store model defaults in app state for later use
        if not hasattr(self.app.state, "model_defaults"):
            self.app.state.model_defaults = {}

        for model_name, defaults_config in model_defaults_value.items():
            if not isinstance(defaults_config, dict):
                warnings.append(
                    f"Model defaults for '{model_name}' is not a dictionary, skipping."
                )
                continue

            try:
                # Validate the model defaults configuration
                model_defaults = ModelDefaults(**defaults_config)
                self.app.state.model_defaults[model_name] = model_defaults
                logger.info(f"Loaded defaults for model: {model_name}")
            except Exception as e:
                warnings.append(f"Invalid model defaults for '{model_name}': {e}")
                continue

        return warnings

    def _parse_and_validate_failover_element(
        self, elem_str: Any, route_name: str
    ) -> tuple[str | None, str | None]:
        """Parses and validates a single failover element string.
        Accepts both slash (backend/model) and colon (backend:model) syntax.
        Returns (valid_element_string, warning_message_if_any).
        """
        if not isinstance(elem_str, str):
            return (
                None,
                f"Invalid element format '{elem_str}' in route '{route_name}', must be string.",
            )

        # Use robust parsing that handles both slash and colon syntax
        from src.core.domain.model_utils import parse_model_backend

        backend_name, model_name = parse_model_backend(elem_str)
        if not backend_name:
            return (
                None,
                f"Invalid element format '{elem_str}' in route '{route_name}', must contain '/' or ':' separator.",
            )

        # Convert to internal colon syntax
        internal_elem_str = f"{backend_name}:{model_name}"

        if backend_name not in self.app.state.functional_backends:
            return (
                None,
                f"Backend '{backend_name}' in route '{route_name}' element '{elem_str}' is not functional, skipping.",
            )

        backend_instance = getattr(self.app.state, f"{backend_name}_backend", None)
        if (
            not backend_instance
            or model_name not in backend_instance.get_available_models()
        ):
            return (
                None,
                f"Model '{model_name}' for backend '{backend_name}' in route '{route_name}' element '{elem_str}' is not available, skipping.",
            )

        return internal_elem_str, None  # Return internal colon syntax, no warning

    def _apply_failover_routes(self, froutes_value: Any) -> list[str]:
        warnings: list[str] = []
        if not isinstance(froutes_value, dict):
            return warnings

        for name, route_config in froutes_value.items():
            if not isinstance(route_config, dict):
                warnings.append(
                    f"Failover route '{name}' config is not a dictionary, skipping."
                )
                continue

            policy = route_config.get("policy", "k")
            elements_config = route_config.get("elements", [])
            valid_elements: list[str] = []

            if not isinstance(elements_config, list):
                warnings.append(
                    f"Elements for failover route '{name}' is not a list, skipping elements."
                )
            else:
                for elem_str in elements_config:
                    valid_element, warning = self._parse_and_validate_failover_element(
                        elem_str, name
                    )
                    if warning:
                        warnings.append(warning)
                    if valid_element:
                        valid_elements.append(valid_element)

            self.app.state.failover_routes[name] = {
                "policy": policy,
                "elements": valid_elements,
            }
        return warnings

    def apply(self, data: dict[str, Any]) -> None:
        all_warnings: list[str] = []

        self._apply_default_backend(data.get("default_backend"))
        self._apply_interactive_mode(data.get("interactive_mode"))
        self._apply_redact_api_keys(data.get("redact_api_keys_in_prompts"))

        failover_warnings = self._apply_failover_routes(data.get("failover_routes"))
        all_warnings.extend(failover_warnings)

        self._apply_command_prefix(data.get("command_prefix"))
        model_defaults_warnings = self._apply_model_defaults(data.get("model_defaults"))
        all_warnings.extend(model_defaults_warnings)

        for w in all_warnings:
            logger.warning(w)

    def collect(self) -> dict[str, Any]:
        # Get interactive mode from session service
        interactive_mode = False
        if hasattr(self.app.state, "service_provider"):
            try:
                from src.core.interfaces.session_service_interface import (
                    ISessionService,
                )

                session_service = self.app.state.service_provider.get_required_service(
                    ISessionService
                )
                interactive_mode = getattr(
                    session_service, "default_interactive_mode", False
                )
            except Exception as e:
                logger.warning(f"Failed to get interactive mode: {e}")

        config_data = {
            "default_backend": self.app.state.backend_type,
            "interactive_mode": interactive_mode,
            "failover_routes": self.app.state.failover_routes,
            "redact_api_keys_in_prompts": self.app.state.api_key_redaction_enabled,
            "command_prefix": self.app.state.command_prefix,
        }

        # Include model defaults if they exist
        if hasattr(self.app.state, "model_defaults") and self.app.state.model_defaults:
            # Convert ModelDefaults objects back to dict format for JSON serialization
            model_defaults_dict = {}
            for model_name, model_defaults in self.app.state.model_defaults.items():
                model_defaults_dict[model_name] = model_defaults.model_dump(
                    exclude_none=True
                )
            config_data["model_defaults"] = model_defaults_dict

        return config_data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = self.collect()
        with self.path.open("w") as f:
            json.dump(data, f, indent=2)
