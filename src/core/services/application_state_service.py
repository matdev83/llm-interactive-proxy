"""
Application state service implementation.

This module provides a concrete implementation of application state interface
that can work with different web frameworks while maintaining abstraction.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, TypeVar, cast

from src.core.domain.configuration.failover_models import FailoverRoute
from src.core.domain.model_utils import ModelDefaults
from src.core.interfaces.application_state_interface import IApplicationState

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class ApplicationStateService(IApplicationState):
    """Service for managing application-wide state through abstraction."""

    def __init__(self, state_provider: Any = None) -> None:
        """Initialize the application state service.

        Args:
            state_provider: Optional state provider (e.g., FastAPI app.state)
        """
        self._state_provider = state_provider
        self._local_state: dict[str, Any] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _is_mock_like(value: Any) -> bool:
        """Return True when value looks like a unittest.mock instance."""
        return value is not None and value.__class__.__module__.startswith(
            "unittest.mock"
        )

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        """Coerce supported types to boolean with stable semantics."""
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, int | float):
            return value != 0
        if isinstance(value, str):
            return bool(value)
        return bool(value)

    def _get_provider_value(self, key: str) -> tuple[bool, Any]:
        """Return provider value with indicator if it is safe to use."""
        if self._state_provider is None:
            return False, None
        try:
            value = getattr(self._state_provider, key)
        except AttributeError:
            return False, None
        if self._is_mock_like(value):
            return False, None
        return True, value

    def _sync_provider_from_local(self) -> None:
        """Copy local state into provider when one becomes available."""
        if self._state_provider is None:
            return
        for key, value in self._local_state.items():
            try:
                setattr(self._state_provider, key, value)
            except Exception:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to synchronize state '%s' to provider '%s'",
                        key,
                        type(self._state_provider).__name__,
                        exc_info=True,
                    )

    def set_state_provider(self, state_provider: Any) -> None:
        """Set the state provider.

        Args:
            state_provider: The state provider (e.g., FastAPI app.state)
        """
        self._state_provider = state_provider
        if state_provider is not None:
            self._sync_provider_from_local()

    def get_command_prefix(self) -> str | None:
        """Get the command prefix."""
        has_value, provider_value = self._get_provider_value("command_prefix")
        if has_value and isinstance(provider_value, str):
            return provider_value
        local_prefix = self._local_state.get("command_prefix")
        return local_prefix if isinstance(local_prefix, str) else None

    def set_command_prefix(self, prefix: str) -> None:
        """Set command prefix."""
        if self._state_provider:
            self._state_provider.command_prefix = prefix
        with self._lock:
            self._local_state["command_prefix"] = prefix

    def get_api_key_redaction_enabled(self) -> bool:
        """Get whether API key redaction is enabled."""
        has_value, provider_value = self._get_provider_value(
            "api_key_redaction_enabled"
        )
        if has_value:
            return self._coerce_bool(provider_value)
        with self._lock:
            return self._coerce_bool(self._local_state.get("api_key_redaction_enabled"))

    def set_api_key_redaction_enabled(self, enabled: bool) -> None:
        """Set whether API key redaction is enabled."""
        if self._state_provider:
            self._state_provider.api_key_redaction_enabled = enabled
        with self._lock:
            self._local_state["api_key_redaction_enabled"] = enabled

    def set_default_api_key_redaction_enabled(self, enabled: bool) -> None:
        """Set default for whether API key redaction is enabled."""
        if self._state_provider:
            # This is a temporary measure to support the legacy persistence model.
            # The attribute is not part of the formal state provider interface.
            self._state_provider.default_api_key_redaction_enabled = enabled
        with self._lock:
            self._local_state["default_api_key_redaction_enabled"] = enabled

    def get_disable_interactive_commands(self) -> bool:
        """Get whether interactive commands are disabled."""
        has_value, provider_value = self._get_provider_value(
            "disable_interactive_commands"
        )
        if has_value:
            return self._coerce_bool(provider_value)
        with self._lock:
            return self._coerce_bool(
                self._local_state.get("disable_interactive_commands")
            )

    def set_disable_interactive_commands(self, disabled: bool) -> None:
        """Set whether interactive commands are disabled."""
        if self._state_provider:
            self._state_provider.disable_interactive_commands = disabled
        with self._lock:
            self._local_state["disable_interactive_commands"] = disabled

    def get_disable_commands(self) -> bool:
        """Get whether commands are disabled."""
        has_value, provider_value = self._get_provider_value("disable_commands")
        if has_value:
            return self._coerce_bool(provider_value)
        with self._lock:
            return self._coerce_bool(self._local_state.get("disable_commands"))

    def set_disable_commands(self, disabled: bool) -> None:
        """Set whether commands are disabled."""
        if self._state_provider:
            self._state_provider.disable_commands = disabled
        with self._lock:
            self._local_state["disable_commands"] = disabled

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a generic setting by key."""
        has_value, provider_value = self._get_provider_value(key)
        if has_value:
            return provider_value
        with self._lock:
            return self._local_state.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        """Set a generic setting by key."""
        if self._state_provider:
            setattr(self._state_provider, key, value)
        with self._lock:
            self._local_state[key] = value

    def get_service(self, service_type: type[_T]) -> _T | None:
        """Retrieve a lazily-constructed or cached service from the provider."""
        service_provider = self.get_setting("service_provider")
        if service_provider is None:
            return None

        getter = getattr(service_provider, "get_service", None)
        if getter is None or not callable(getter):
            return None

        try:
            return cast(_T | None, getter(service_type))
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "ApplicationStateService failed to resolve service '%s'",
                    getattr(service_type, "__name__", repr(service_type)),
                    exc_info=True,
                )
            return None

    # --- Feature flags (scaffold) ---
    def get_use_failover_strategy(self) -> bool:
        """Get whether to use the extracted failover strategy (default: False)."""
        # Prefer explicit state; avoid env reads in hot paths for determinism
        return bool(self.get_setting("PROXY_USE_FAILOVER_STRATEGY", False))

    def set_use_failover_strategy(self, enabled: bool) -> None:
        """Enable or disable failover strategy usage."""
        self.set_setting("PROXY_USE_FAILOVER_STRATEGY", enabled)

    def get_use_streaming_pipeline(self) -> bool:
        """Whether to use the streaming pipeline (default: False)."""
        return bool(self.get_setting("PROXY_USE_STREAMING_PIPELINE", False))

    def set_use_streaming_pipeline(self, enabled: bool) -> None:
        """Enable or disable the streaming pipeline usage."""
        self.set_setting("PROXY_USE_STREAMING_PIPELINE", enabled)

    def get_functional_backends(self) -> list[str]:
        """Get list of functional backends."""

        def _normalize_backends(value: Any) -> list[str]:
            if isinstance(value, list):
                return value
            if isinstance(value, set):
                return list(value)
            if isinstance(value, tuple):
                return list(value)
            return []

        has_value, provider_value = self._get_provider_value("functional_backends")
        if has_value:
            return _normalize_backends(provider_value)
        with self._lock:
            local_backends = self._local_state.get("functional_backends", [])
            return _normalize_backends(local_backends)

    def set_functional_backends(self, backends: list[str]) -> None:
        """Set list of functional backends."""
        if self._state_provider:
            self._state_provider.functional_backends = backends
        with self._lock:
            self._local_state["functional_backends"] = backends

    def get_backend_type(self) -> str | None:
        """Get current backend type."""
        has_value, provider_value = self._get_provider_value("backend_type")
        if has_value and isinstance(provider_value, str):
            return provider_value
        with self._lock:
            local_backend_type = self._local_state.get("backend_type")
            return local_backend_type if isinstance(local_backend_type, str) else None

    def set_backend_type(self, backend_type: str | None) -> None:
        """Set current backend type."""
        if self._state_provider:
            self._state_provider.backend_type = backend_type
        with self._lock:
            self._local_state["backend_type"] = backend_type

    def get_backend(self) -> Any:
        """Get current backend instance."""
        has_value, provider_value = self._get_provider_value("backend")
        if has_value:
            return provider_value
        with self._lock:
            return self._local_state.get("backend")

    def set_backend(self, backend: Any) -> None:
        """Set current backend instance."""
        if self._state_provider:
            self._state_provider.backend = backend
        with self._lock:
            self._local_state["backend"] = backend

    def get_model_defaults(self) -> dict[str, ModelDefaults]:
        """Get model defaults."""
        has_value, provider_value = self._get_provider_value("model_defaults")
        if has_value and isinstance(provider_value, dict):
            return cast(dict[str, ModelDefaults], provider_value)
        with self._lock:
            local_defaults = self._local_state.get("model_defaults", {})
            return cast(
                dict[str, ModelDefaults],
                local_defaults if isinstance(local_defaults, dict) else {},
            )

    def set_model_defaults(self, defaults: dict[str, ModelDefaults]) -> None:
        """Set model defaults."""
        if self._state_provider:
            self._state_provider.model_defaults = defaults
        with self._lock:
            self._local_state["model_defaults"] = defaults

    def get_failover_routes(self) -> list[FailoverRoute] | None:
        """Get failover routes."""

        def _to_models(routes_data: Any) -> list[FailoverRoute] | None:
            if not routes_data:
                return None
            if isinstance(routes_data, dict):
                result = []
                for name, config in routes_data.items():
                    if isinstance(config, dict):
                        # Ensure name is included in the model
                        result.append(FailoverRoute(name=name, **config))
                    elif isinstance(config, FailoverRoute):
                        result.append(config)
                return result if result else None
            if isinstance(routes_data, list):
                result = []
                for item in routes_data:
                    if isinstance(item, dict):
                        result.append(FailoverRoute(**item))
                    elif isinstance(item, FailoverRoute):
                        result.append(item)
                return result if result else None
            return None

        has_value, provider_value = self._get_provider_value("failover_routes")
        if has_value:
            return _to_models(provider_value)

        with self._lock:
            local_routes = self._local_state.get("failover_routes")
            return _to_models(local_routes)

    def set_failover_route(self, name: str, route_config: dict[str, Any]) -> None:
        """Set a failover route."""
        # Clean config to avoid redundant 'name' if present
        clean_config = {k: v for k, v in route_config.items() if k != "name"}

        if self._state_provider:
            if not hasattr(self._state_provider, "failover_routes"):
                self._state_provider.failover_routes = {}
            self._state_provider.failover_routes[name] = clean_config
        with self._lock:
            if "failover_routes" not in self._local_state:
                self._local_state["failover_routes"] = {}
            self._local_state["failover_routes"][name] = clean_config

    def set_failover_routes(self, routes: list[FailoverRoute]) -> None:
        """Set multiple failover routes."""
        routes_dict = {}
        for route in routes:
            if isinstance(route, dict):
                if "name" in route:
                    name = route["name"]
                    routes_dict[name] = {k: v for k, v in route.items() if k != "name"}
                continue

            if hasattr(route, "name"):
                routes_dict[route.name] = route.model_dump(exclude={"name"})

        if self._state_provider:
            self._state_provider.failover_routes = routes_dict
        else:
            with self._lock:
                self._local_state["failover_routes"] = routes_dict
