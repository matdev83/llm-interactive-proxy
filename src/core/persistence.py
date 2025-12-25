from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI

from src.command_prefix import validate_command_prefix
from src.core.common.exceptions import (
    BackendError,
    ConfigurationError,
    JSONParsingError,
    ServiceResolutionError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.model_utils import ModelDefaults, parse_model_backend
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FailoverValidationResult:
    """Outcome of validating a failover backend/model combination."""

    is_valid: bool
    warning: str | None = None


class ConfigIOProtocol(Protocol):
    """Protocol for reading and writing configuration data."""

    def exists(self) -> bool:
        """Return True when the underlying resource exists."""
        ...

    def read(self) -> dict[str, Any]:
        """Read configuration data as a dictionary."""
        ...

    def write(self, data: dict[str, Any]) -> None:
        """Persist configuration data."""
        ...


class FileConfigIO(ConfigIOProtocol):
    """File-backed configuration storage with JSON encoding."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def exists(self) -> bool:
        return self._path.is_file()

    def read(self) -> dict[str, Any]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error(
                "Failed to read config file %s: %s", self._path, exc, exc_info=True
            )
            raise ConfigurationError(
                f"Failed to read config file {self._path.name}."
            ) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error(
                "Failed to parse config file %s as JSON: %s",
                self._path,
                exc,
                exc_info=True,
            )
            raise JSONParsingError(
                f"Failed to parse config file {self._path.name} as JSON."
            ) from exc

        if not isinstance(data, dict):
            logger.error(
                "Invalid config file structure in %s: expected object but got %s",
                self._path,
                type(data).__name__,
            )
            raise ConfigurationError(
                f"Config file {self._path.name} must contain a JSON object."
            )

        return data

    def write(self, data: dict[str, Any]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
        except OSError as exc:
            logger.error(
                "Failed to write config file %s: %s", self._path, exc, exc_info=True
            )
            raise ConfigurationError(
                f"Failed to write config file {self._path.name}."
            ) from exc
        except TypeError as exc:
            logger.error(
                "Failed to serialize config data to JSON for %s: %s",
                self._path,
                exc,
                exc_info=True,
            )
            raise ConfigurationError(
                f"Failed to serialize configuration to JSON for {self._path.name}."
            ) from exc


class BackendBinderProtocol(Protocol):
    """Protocol for binding backend instances into application state."""

    def bind(self, backend_name: str, *, strict: bool) -> None:
        """Ensure the backend instance is wired up for the provided backend name."""
        ...


class NoOpBackendBinder(BackendBinderProtocol):
    """A no-op binder for when a real binder is not available."""

    def bind(self, backend_name: str, *, strict: bool) -> None:
        """A no-op binder for when a real binder is not available."""


class ServiceProviderBackendBinder(BackendBinderProtocol):
    """Binder that resolves backend instances through the service provider."""

    def __init__(
        self,
        service_provider: IServiceProvider | None,
        app_state: IApplicationState | None,
    ) -> None:
        self._service_provider = service_provider
        self._app_state = app_state

    def bind(self, backend_name: str, *, strict: bool) -> None:
        if not self._service_provider or not self._app_state:
            return

        try:
            from src.core.interfaces.backend_service_interface import (
                IBackendService,
            )

            backend_service = self._service_provider.get_required_service(
                IBackendService  # type: ignore[type-abstract]
            )
        except ServiceResolutionError as exc:
            logger.debug(
                "DI resolution for IBackendService failed: %s", exc, exc_info=True
            )
            if strict:
                raise ServiceResolutionError(
                    "Failed to resolve IBackendService for default backend."
                ) from exc
            logger.warning(
                "Could not resolve IBackendService while applying default backend '%s'; "
                "continuing without binding backend instance",
                backend_name,
            )
            return

        try:
            backend_instance = backend_service.get_backend(backend_name)
        except BackendError as exc:
            if strict:
                raise ConfigurationError(
                    f"Failed to resolve backend instance for '{backend_name}'."
                ) from exc
            logger.warning(
                "Failed to resolve backend instance for '%s': %s",
                backend_name,
                exc,
            )
            return
        except Exception as exc:  # pragma: no cover - defensive best effort
            if strict:
                raise ConfigurationError(
                    "Unexpected error while binding backend instance."
                ) from exc
            logger.warning(
                "Unexpected error while binding backend '%s': %s",
                backend_name,
                exc,
            )
            return

        self._app_state.set_backend(backend_instance)


class FailoverRouteValidatorProtocol(Protocol):
    """Protocol for validating failover backend/model combinations."""

    def validate(self, backend_name: str, model_name: str) -> FailoverValidationResult:
        """Validate backend/model compatibility."""
        ...


class NoOpFailoverRouteValidator(FailoverRouteValidatorProtocol):
    """Validator that always reports success (useful for tests)."""

    def validate(self, backend_name: str, model_name: str) -> FailoverValidationResult:
        return FailoverValidationResult(is_valid=True, warning=None)


class ServiceProviderFailoverRouteValidator(FailoverRouteValidatorProtocol):
    """Validator that uses backend service validation when available."""

    def __init__(
        self,
        service_provider: IServiceProvider | None,
        strict_error_supplier: Callable[[], bool],
    ) -> None:
        self._service_provider = service_provider
        self._strict_error_supplier = strict_error_supplier

    def validate(self, backend_name: str, model_name: str) -> FailoverValidationResult:
        if not self._service_provider:
            return FailoverValidationResult(is_valid=True, warning=None)

        try:
            from src.core.interfaces.backend_service_interface import (
                IBackendService,
            )

            backend_service = self._service_provider.get_required_service(
                IBackendService  # type: ignore[type-abstract]
            )
        except ServiceResolutionError as exc:
            logger.debug(
                "DI resolution for IBackendService failed in failover validation: %s",
                exc,
                exc_info=True,
            )
            if self._strict_error_supplier():
                raise ServiceResolutionError(
                    "Failed to resolve IBackendService during failover validation",
                    service_name="IBackendService",
                ) from exc
            return FailoverValidationResult(
                is_valid=True,
                warning=(
                    "Skipping backend validation because the backend service is unavailable."
                ),
            )

        coroutine = backend_service.validate_backend_and_model(backend_name, model_name)

        try:
            asyncio.get_running_loop()
            loop_running = True
        except RuntimeError:
            loop_running = False

        if loop_running:
            warning = (
                f"Skipping validation for backend '{backend_name}' model '{model_name}' "
                "because the event loop is already running."
            )
            if self._strict_error_supplier():
                raise ConfigurationError(
                    "Cannot validate failover routes while the event loop is running."
                )
            return FailoverValidationResult(is_valid=True, warning=warning)

        try:
            is_valid, message = asyncio.run(coroutine)
        except BackendError as exc:
            if self._strict_error_supplier():
                raise ConfigurationError(
                    f"Backend validation failed for '{backend_name}'."
                ) from exc
            logger.debug(
                "Backend validation failed for %s/%s: %s",
                backend_name,
                model_name,
                exc,
                exc_info=True,
            )
            return FailoverValidationResult(is_valid=False, warning=str(exc))
        except Exception as exc:
            if self._strict_error_supplier():
                raise ConfigurationError(
                    "Unexpected error validating failover element."
                ) from exc
            logger.debug(
                "Unexpected error validating failover element %s/%s: %s",
                backend_name,
                model_name,
                exc,
                exc_info=True,
            )
            return FailoverValidationResult(
                is_valid=False,
                warning=str(exc),
            )

        if not is_valid:
            warning = message or (
                f"Model '{model_name}' is not available for backend '{backend_name}'."
            )
            return FailoverValidationResult(is_valid=False, warning=warning)

        return FailoverValidationResult(is_valid=True, warning=None)


class ConfigManager:
    """Co-ordinates persistence of runtime configuration settings."""

    def __init__(
        self,
        app: FastAPI | None,
        path: str,
        service_provider: IServiceProvider | None = None,
        app_state: IApplicationState | None = None,
        config: AppConfig | None = None,
        *,
        config_io: ConfigIOProtocol | None = None,
        backend_binder: BackendBinderProtocol | None = None,
        failover_validator: FailoverRouteValidatorProtocol | None = None,
    ) -> None:
        self.app = app
        self.path = Path(path)
        self.service_provider = service_provider
        self.app_state = app_state
        self.config = config
        self._config_io = config_io or FileConfigIO(self.path)

        self._backend_binder: BackendBinderProtocol
        if backend_binder is not None:
            self._backend_binder = backend_binder
        elif app_state is not None and service_provider is not None:
            self._backend_binder = ServiceProviderBackendBinder(
                service_provider, app_state
            )
        else:
            self._backend_binder = NoOpBackendBinder()

        self._failover_validator: FailoverRouteValidatorProtocol
        if failover_validator is not None:
            self._failover_validator = failover_validator
        else:
            self._failover_validator = ServiceProviderFailoverRouteValidator(
                service_provider, self._should_raise_strict_errors
            )

    def _should_raise_strict_errors(self) -> bool:
        if self.config:
            value = self.config.get("session.dangerous_command_prevention_enabled")
            return bool(value) if value is not None else False
        return False

    def load(self) -> None:
        if not self._config_io.exists():
            return
        data = self._config_io.read()
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

        cli_backend = (
            self.config.get("backends.default_backend") if self.config else None
        )
        if cli_backend and cli_backend != backend_value:
            logger.info(
                "Skipping config file backend '%s' because CLI argument '%s' takes precedence",
                backend_value,
                cli_backend,
            )
            return

        self.app_state.set_backend_type(backend_value)

        strict_errors = self._should_raise_strict_errors()
        if self._backend_binder:
            self._backend_binder.bind(backend_value, strict=strict_errors)

    def _apply_interactive_mode(self, mode_value: Any) -> None:
        if not isinstance(mode_value, bool) or self.service_provider is None:
            return

        try:
            from src.core.interfaces.session_service_interface import (
                ISessionService,
            )

            session_service = self.service_provider.get_required_service(
                ISessionService  # type: ignore[type-abstract]
            )
            session_service.default_interactive_mode = mode_value  # type: ignore[attr-defined]
        except ServiceResolutionError as exc:
            logger.debug(
                "DI resolution for ISessionService failed: %s", exc, exc_info=True
            )
            if self._should_raise_strict_errors():
                raise ServiceResolutionError(
                    "Failed to resolve ISessionService for interactive mode."
                ) from exc
            logger.warning(
                "Could not resolve ISessionService while applying interactive mode; "
                "continuing without updating session service",
            )
        except Exception as exc:
            logger.error(
                "An unexpected error occurred during DI resolution for ISessionService: %s",
                exc,
                exc_info=True,
            )
            if self._should_raise_strict_errors():
                raise ConfigurationError(
                    "An unexpected error occurred while applying interactive mode."
                ) from exc
            logger.warning("Skipping interactive mode update due to unexpected error")

    def _apply_redact_api_keys(self, redact_value: Any) -> None:
        if isinstance(redact_value, bool) and self.app_state:
            self.app_state.set_api_key_redaction_enabled(redact_value)
            self.app_state.set_default_api_key_redaction_enabled(redact_value)

    def _apply_command_prefix(self, prefix_value: Any) -> None:
        if isinstance(prefix_value, str) and self.app_state:
            err = validate_command_prefix(prefix_value)
            if err:
                logger.warning("Invalid command prefix in config: %s", err)
                return
            self.app_state.set_command_prefix(prefix_value)

    def _apply_model_defaults(self, model_defaults_value: Any) -> list[str]:
        warnings: list[str] = []
        if not isinstance(model_defaults_value, dict):
            return warnings
        if not self.app_state:
            return warnings

        current_defaults = dict(self.app_state.get_model_defaults() or {})

        for model_name, defaults_config in model_defaults_value.items():
            if not isinstance(defaults_config, dict):
                warnings.append(
                    f"Model defaults for '{model_name}' is not a dictionary, skipping."
                )
                continue

            try:
                model_defaults = ModelDefaults(**defaults_config)
            except Exception as exc:
                logger.error(
                    "Invalid model defaults for '%s': %s",
                    model_name,
                    exc,
                    exc_info=True,
                )
                warnings.append(
                    f"Invalid model defaults for '{model_name}': {exc}. Check logs for details."
                )
                continue

            current_defaults[model_name] = model_defaults

        self.app_state.set_model_defaults(current_defaults)
        return warnings

    def _parse_and_validate_failover_element(
        self, elem_str: Any, route_name: str
    ) -> tuple[str | None, str | None]:
        if not isinstance(elem_str, str):
            return (
                None,
                f"Invalid element format '{elem_str}' in route '{route_name}', must be string.",
            )

        backend_name, model_name = parse_model_backend(elem_str)
        if not backend_name or not model_name:
            return (
                None,
                f"Invalid element format '{elem_str}' in route '{route_name}', must be in 'backend:model' format.",
            )

        if self.app_state and backend_name not in set(
            self.app_state.get_functional_backends()
        ):
            return (
                None,
                f"Backend '{backend_name}' in route '{route_name}' element '{elem_str}' is not functional, skipping.",
            )

        validator = self._failover_validator or NoOpFailoverRouteValidator()
        result = validator.validate(backend_name, model_name)

        if not result.is_valid:
            warning = result.warning or (
                f"Model '{model_name}' for backend '{backend_name}' is not available."
            )
            return (
                None,
                f"Model '{model_name}' for backend '{backend_name}' in route '{route_name}' element '{elem_str}' is not available: {warning}",
            )

        if result.warning:
            return f"{backend_name}:{model_name}", result.warning

        return f"{backend_name}:{model_name}", None

    def _prune_unavailable_routes(self) -> None:
        if not self.app_state or not self.app_state.app_config:
            return

        self.app_state.app_config.failover_routes = {
            name: route
            for name, route in self.app_state.app_config.failover_routes.items()
            if (route.elements if hasattr(route, "elements") else route.get("elements"))
            and all(
                self.app_state.app_config.model_is_functional(element)
                for element in (
                    route.elements if hasattr(route, "elements") else route.get("elements", [])
                )
            )
        }

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

        backends_data = data.get("backends", {})
        session_data = data.get("session", {})
        auth_data = data.get("auth", {})

        if isinstance(backends_data, dict):
            self._apply_default_backend(backends_data.get("default_backend"))

        if isinstance(session_data, dict):
            self._apply_interactive_mode(session_data.get("default_interactive_mode"))

        if isinstance(auth_data, dict):
            self._apply_redact_api_keys(auth_data.get("redact_api_keys_in_prompts"))

        failover_warnings = self._apply_failover_routes(data.get("failover_routes"))
        all_warnings.extend(failover_warnings)

        self._apply_command_prefix(data.get("command_prefix"))
        model_defaults_warnings = self._apply_model_defaults(data.get("model_defaults"))
        all_warnings.extend(model_defaults_warnings)

        for warning in all_warnings:
            logger.warning(warning)

    def collect(self) -> dict[str, Any]:
        if not self.app_state or not self.app_state.app_config:
            return {}

        # Get backend configurations
        backends_data = self.app_state.app_config.backends.model_dump(
            exclude_none=True, exclude_defaults=True
        )
        # Ensure the live default_backend is saved
        backends_data["default_backend"] = self.app_state.get_backend_type()

        # Get session configuration
        interactive_mode = False
        if self.service_provider:
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
            except ServiceResolutionError as exc:
                logger.warning(
                    "Failed to get interactive mode for persistence: %s", exc
                )
            except Exception as exc:
                logger.warning(
                    "Unexpected error getting interactive mode for persistence: %s", exc
                )
        session_data = {"default_interactive_mode": interactive_mode}

        # Get auth configuration
        auth_data = {
            "redact_api_keys_in_prompts": self.app_state.get_api_key_redaction_enabled()
        }

        # Get model defaults
        model_defaults_data: dict[str, Any] = {}
        model_defaults = self.app_state.get_model_defaults()
        if model_defaults:
            for model_name, model_defaults_obj in model_defaults.items():
                if hasattr(model_defaults_obj, "model_dump"):
                    model_defaults_data[model_name] = model_defaults_obj.model_dump(
                        exclude_none=True
                    )
                else:
                    model_defaults_data[model_name] = model_defaults_obj

        # Get failover routes and convert to dict for persistence
        failover_routes_data = {}
        routes_list = self.app_state.get_failover_routes()
        if routes_list:
            for route in routes_list:
                if hasattr(route, "model_dump"):
                    failover_routes_data[route.name] = route.model_dump(exclude={"name"})
                elif isinstance(route, dict) and "name" in route:
                    failover_routes_data[route["name"]] = {
                        k: v for k, v in route.items() if k != "name"
                    }

        config_data: dict[str, Any] = {
            "backends": backends_data,
            "session": session_data,
            "auth": auth_data,
            "failover_routes": failover_routes_data,
            "command_prefix": self.app_state.get_command_prefix(),
            "model_defaults": model_defaults_data,
        }

        # Clean up empty sections
        return {k: v for k, v in config_data.items() if v}

    def save(self) -> None:
        data = self.collect()
        self._config_io.write(data)
