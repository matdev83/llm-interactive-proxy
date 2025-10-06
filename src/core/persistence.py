import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from src.command_prefix import validate_command_prefix
from src.core.common.exceptions import (
    ConfigurationError,
    JSONParsingError,
    ServiceResolutionError,
)
from src.core.domain.model_utils import (
    ModelDefaults,  # Add import for model config classes
)
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def _get_strict_persistence_errors() -> bool:
    """Get strict persistence errors setting from environment."""
    return os.getenv("STRICT_PERSISTENCE_ERRORS", "false").lower() in (
        "true",
        "1",
        "yes",
    )


class ConfigManager:
    def __init__(
        self,
        app: FastAPI,
        path: str,
        service_provider: IServiceProvider | None = None,
        app_state: IApplicationState | None = None,
    ) -> None:
        self.app = app
        self.path = Path(path)
        self.service_provider = service_provider
        self.app_state = app_state

    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text())
        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse config file %s as JSON: %s",
                self.path,
                e,
                exc_info=True,
            )
            raise JSONParsingError(
                f"Failed to parse config file {self.path.name} as JSON."
            ) from e
        except OSError as e:
            logger.error(
                "Failed to read config file %s: %s", self.path, e, exc_info=True
            )
            raise ConfigurationError(
                f"Failed to read config file {self.path.name}."
            ) from e
        except Exception as e:  # Catch any other unexpected exceptions
            logger.error(
                "An unexpected error occurred while loading config file %s: %s",
                self.path,
                e,
                exc_info=True,
            )
            raise ConfigurationError(
                f"An unexpected error occurred while loading config file {self.path.name}."
            ) from e
        self.apply(data)

    def _apply_default_backend(self, backend_value: Any) -> None:
        if not isinstance(backend_value, str):
            return

        if not self.app_state:
            return

        functional_backends = set(self.app_state.get_functional_backends())
        if backend_value not in functional_backends:
            raise ConfigurationError(
                message=(
                    f"Default backend '{backend_value}' is not in functional_backends."
                ),
                details={
                    "backend": backend_value,
                    "functional_backends": sorted(functional_backends),
                },
            )

        cli_backend = os.getenv("LLM_BACKEND")
        if cli_backend and cli_backend != backend_value:
            logger.info(
                "Skipping config file backend '%s' because CLI argument '%s' takes precedence",
                backend_value,
                cli_backend,
            )
            return

        self.app_state.set_backend_type(backend_value)
        if self.service_provider is not None:
            try:
                from src.core.interfaces.backend_service_interface import (
                    IBackendService,
                )

                backend_service = self.service_provider.get_required_service(
                    IBackendService  # type: ignore[type-abstract]
                )
                if backend_service and backend_value in getattr(
                    backend_service, "_backends", {}  # type: ignore[attr-defined]
                ):
                    self.app_state.set_backend(
                        backend_service._backends[  # type: ignore[attr-defined]
                            backend_value
                        ]
                    )
                    return
            except ServiceResolutionError as e:
                logger.debug(
                    "DI resolution for IBackendService failed: %s",
                    e,
                    exc_info=True,
                )
                if _get_strict_persistence_errors():
                    raise ServiceResolutionError(
                        "Failed to resolve IBackendService for default backend."
                    ) from e
                logger.warning(
                    "Could not resolve IBackendService while applying default backend '%s'; "
                    "continuing without binding backend instance",
                    backend_value,
                )
            except Exception as e:
                logger.error(
                    "An unexpected error occurred during DI resolution for IBackendService: %s",
                    e,
                    exc_info=True,
                )
                if _get_strict_persistence_errors():
                    raise ConfigurationError(
                        "An unexpected error occurred while applying default backend."
                    ) from e
                logger.warning(
                    "Skipping backend instance binding for default backend '%s' due to unexpected error",
                    backend_value,
                )

    def _apply_interactive_mode(self, mode_value: Any) -> None:
        if isinstance(mode_value, bool) and self.service_provider is not None:
            # Get session service from DI
            try:
                from src.core.interfaces.session_service_interface import (
                    ISessionService,
                )

                session_service = self.service_provider.get_required_service(
                    ISessionService  # type: ignore[type-abstract]
                )
                session_service.default_interactive_mode = mode_value  # type: ignore[attr-defined]
            except ServiceResolutionError as e:
                logger.debug(
                    "DI resolution for ISessionService failed: %s",
                    e,
                    exc_info=True,
                )
                if _get_strict_persistence_errors():
                    raise ServiceResolutionError(
                        "Failed to resolve ISessionService for interactive mode."
                    ) from e
                logger.warning(
                    "Could not resolve ISessionService while applying interactive mode; "
                    "continuing without updating session service",
                )
            except Exception as e:
                logger.error(
                    "An unexpected error occurred during DI resolution for ISessionService: %s",
                    e,
                    exc_info=True,
                )
                if _get_strict_persistence_errors():
                    raise ConfigurationError(
                        "An unexpected error occurred while applying interactive mode."
                    ) from e
                logger.warning(
                    "Skipping interactive mode update due to unexpected error",
                )

    def _apply_redact_api_keys(self, redact_value: Any) -> None:
        if isinstance(redact_value, bool) and self.app_state:
            self.app_state.set_api_key_redaction_enabled(redact_value)
            # Note: default_api_key_redaction_enabled is not in the interface yet
            # We'll need to add it or handle it differently
            if (
                self.app_state
                and hasattr(self.app_state, "_state_provider")
                and self.app_state._state_provider
            ):
                self.app_state._state_provider.default_api_key_redaction_enabled = (
                    redact_value
                )

    def _apply_command_prefix(self, prefix_value: Any) -> None:
        if isinstance(prefix_value, str):
            err = validate_command_prefix(prefix_value)
            if err:
                logger.warning(f"Invalid command prefix in config: {err}")
            else:
                if self.app_state:
                    self.app_state.set_command_prefix(prefix_value)

    def _apply_model_defaults(self, model_defaults_value: Any) -> list[str]:
        """Apply model-specific default configurations."""
        warnings: list[str] = []
        if not isinstance(model_defaults_value, dict):
            return warnings

        # Store model defaults in app state for later use
        if self.app_state and not hasattr(self.app_state, "model_defaults"):
            self.app_state.set_model_defaults({})

        for model_name, defaults_config in model_defaults_value.items():
            if not isinstance(defaults_config, dict):
                warnings.append(
                    f"Model defaults for '{model_name}' is not a dictionary, skipping."
                )
                continue

            try:
                # Validate the model defaults configuration
                model_defaults = ModelDefaults(**defaults_config)
                if self.app_state:
                    current_defaults = self.app_state.get_model_defaults()
                    current_defaults[model_name] = model_defaults
                    self.app_state.set_model_defaults(current_defaults)
                logger.info(f"Loaded defaults for model: {model_name}")
            except Exception as e:
                logger.error(
                    "Invalid model defaults for '%s': %s",
                    model_name,
                    e,
                    exc_info=True,
                )
                warnings.append(
                    f"Invalid model defaults for '{model_name}': {e}. Check logs for details."
                )
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
        if not backend_name or not model_name:
            return (
                None,
                f"Invalid element format '{elem_str}' in route '{route_name}', must contain '/' or ':' separator.",
            )

        # Convert to internal colon syntax
        internal_elem_str = f"{backend_name}:{model_name}"

        if (
            self.app_state
            and backend_name not in self.app_state.get_functional_backends()
        ):
            return (
                None,
                f"Backend '{backend_name}' in route '{route_name}' element '{elem_str}' is not functional, skipping.",
            )

        valid_model = True
        validation_warning: str | None = None
        if self.service_provider:
            try:
                from src.core.interfaces.backend_service_interface import (
                    IBackendService,
                )

                backend_service = self.service_provider.get_required_service(
                    IBackendService  # type: ignore[type-abstract]
                )
                if backend_service:
                    # This is now an async method, but we are in a sync method.
                    # This is a bigger issue that needs to be addressed separately.
                    # For now, we will assume it's valid if the service exists.
                    # A proper fix would involve making this method async.
                    # This is a temporary workaround to unblock the current refactoring.
                    import asyncio

                    try:
                        valid_model, _validation_error = asyncio.run(
                            backend_service.validate_backend_and_model(
                                backend_name, model_name
                            )
                        )
                    except RuntimeError as runtime_error:
                        message = str(runtime_error)
                        if "asyncio.run() cannot be called" not in message:
                            raise

                        logger.debug(
                            "Skipping failover validation for %s/%s because the event loop is running.",
                            backend_name,
                            model_name,
                            exc_info=True,
                        )
                        if _get_strict_persistence_errors():
                            raise ConfigurationError(
                                "Cannot validate failover routes while the event loop is running."
                            ) from runtime_error
                        validation_warning = (
                            f"Skipping validation for backend '{backend_name}' model '{model_name}' in route "
                            f"'{route_name}' because the event loop is already running."
                        )
                        valid_model = True

            except ServiceResolutionError as e:
                logger.debug(
                    "DI resolution for IBackendService failed in failover validation: %s",
                    e,
                    exc_info=True,
                )
                if _get_strict_persistence_errors():
                    raise ServiceResolutionError(
                        "Failed to resolve IBackendService during failover validation",
                        service_name="IBackendService",
                    ) from e
            except Exception as e:
                logger.debug(
                    "Unexpected error during DI resolution in failover validation: %s",
                    e,
                    exc_info=True,
                )
                if _get_strict_persistence_errors():
                    raise ConfigurationError(
                        "Unexpected error validating failover element",
                    ) from e
                valid_model = False

        if not valid_model:
            return (
                None,
                f"Model '{model_name}' for backend '{backend_name}' in route '{route_name}' element '{elem_str}' is not available, skipping.",
            )

        if validation_warning:
            return internal_elem_str, validation_warning

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

            if self.app_state:
                self.app_state.set_failover_route(
                    name,
                    {
                        "policy": policy,
                        "elements": valid_elements,
                    },
                )
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
        if self.service_provider is not None:
            try:
                from src.core.interfaces.session_service_interface import (
                    ISessionService,
                )

                session_service = self.service_provider.get_required_service(
                    ISessionService  # type: ignore[type-abstract]
                )
                interactive_mode = getattr(
                    session_service, "default_interactive_mode", False
                )
            except ServiceResolutionError as e:
                if _get_strict_persistence_errors():
                    raise
                logger.warning(f"Failed to get interactive mode: {e}")
            except Exception as e:
                if _get_strict_persistence_errors():
                    raise ConfigurationError(
                        "Unexpected error reading interactive mode from session service."
                    ) from e
                logger.warning(f"Failed to get interactive mode: {e}")

        config_data: dict[str, Any] = {
            "default_backend": (
                self.app_state.get_backend_type() if self.app_state else None
            ),
            "interactive_mode": interactive_mode,
            "failover_routes": (
                self.app_state.get_failover_routes() if self.app_state else {}
            ),
            "redact_api_keys_in_prompts": (
                self.app_state.get_api_key_redaction_enabled()
                if self.app_state
                else False
            ),
            "command_prefix": (
                self.app_state.get_command_prefix() if self.app_state else None
            ),
        }

        # Include model defaults if they exist
        if self.app_state:
            model_defaults = self.app_state.get_model_defaults()
            if model_defaults:
                # Convert ModelDefaults objects back to dict format for JSON serialization
                model_defaults_dict = {}
                for model_name, model_defaults_obj in model_defaults.items():
                    if hasattr(model_defaults_obj, "model_dump"):
                        model_defaults_dict[model_name] = model_defaults_obj.model_dump(
                            exclude_none=True
                        )
                    else:
                        model_defaults_dict[model_name] = model_defaults_obj
                config_data["model_defaults"] = model_defaults_dict

        return config_data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = self.collect()
        try:
            with self.path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError as e:
            logger.error(
                "Failed to write config file %s: %s", self.path, e, exc_info=True
            )
            raise ConfigurationError(
                f"Failed to write config file {self.path.name}."
            ) from e
        except TypeError as e:
            logger.error(
                "Failed to serialize config data to JSON for %s: %s",
                self.path,
                e,
                exc_info=True,
            )
            raise ConfigurationError(
                f"Failed to serialize configuration to JSON for {self.path.name}."
            ) from e
