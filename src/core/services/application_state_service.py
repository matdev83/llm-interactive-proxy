"""
Application state service implementation.

This module provides a concrete implementation of the application state interface
that can work with different web frameworks while maintaining abstraction.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.application_state_interface import IApplicationState

logger = logging.getLogger(__name__)


class ApplicationStateService(IApplicationState):
    """Service for managing application-wide state through abstraction."""

    def __init__(self, state_provider: Any = None) -> None:
        """Initialize the application state service.

        Args:
            state_provider: Optional state provider (e.g., FastAPI app.state)
        """
        self._state_provider = state_provider
        self._local_state: dict[str, Any] = {}

    def set_state_provider(self, state_provider: Any) -> None:
        """Set the state provider.

        Args:
            state_provider: The state provider (e.g., FastAPI app.state)
        """
        self._state_provider = state_provider

    def get_command_prefix(self) -> str | None:
        """Get the command prefix."""
        if self._state_provider and hasattr(self._state_provider, "command_prefix"):
            prefix = self._state_provider.command_prefix
            return prefix if isinstance(prefix, str) else None
        local_prefix = self._local_state.get("command_prefix")
        return local_prefix if isinstance(local_prefix, str) else None

    def set_command_prefix(self, prefix: str) -> None:
        """Set the command prefix."""
        if self._state_provider:
            self._state_provider.command_prefix = prefix
        self._local_state["command_prefix"] = prefix

    def get_api_key_redaction_enabled(self) -> bool:
        """Get whether API key redaction is enabled."""
        if self._state_provider and hasattr(
            self._state_provider, "api_key_redaction_enabled"
        ):
            return bool(self._state_provider.api_key_redaction_enabled)
        return bool(self._local_state.get("api_key_redaction_enabled", False))

    def set_api_key_redaction_enabled(self, enabled: bool) -> None:
        """Set whether API key redaction is enabled."""
        if self._state_provider:
            self._state_provider.api_key_redaction_enabled = enabled
        self._local_state["api_key_redaction_enabled"] = enabled

    def get_disable_interactive_commands(self) -> bool:
        """Get whether interactive commands are disabled."""
        if self._state_provider and hasattr(
            self._state_provider, "disable_interactive_commands"
        ):
            return bool(self._state_provider.disable_interactive_commands)
        return bool(self._local_state.get("disable_interactive_commands", False))

    def set_disable_interactive_commands(self, disabled: bool) -> None:
        """Set whether interactive commands are disabled."""
        if self._state_provider:
            self._state_provider.disable_interactive_commands = disabled
        self._local_state["disable_interactive_commands"] = disabled

    def get_disable_commands(self) -> bool:
        """Get whether commands are disabled."""
        if self._state_provider and hasattr(self._state_provider, "disable_commands"):
            return bool(self._state_provider.disable_commands)
        return bool(self._local_state.get("disable_commands", False))

    def set_disable_commands(self, disabled: bool) -> None:
        """Set whether commands are disabled."""
        if self._state_provider:
            self._state_provider.disable_commands = disabled
        self._local_state["disable_commands"] = disabled

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a generic setting by key."""
        if self._state_provider and hasattr(self._state_provider, key):
            return getattr(self._state_provider, key)
        return self._local_state.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        """Set a generic setting by key."""
        if self._state_provider:
            setattr(self._state_provider, key, value)
        self._local_state[key] = value

    # --- Feature flags (scaffold) ---
    def get_use_failover_strategy(self) -> bool:
        """Get whether to use the extracted failover strategy (default: False)."""
        # Prefer explicit state; avoid env reads in hot paths for determinism
        return bool(self.get_setting("PROXY_USE_FAILOVER_STRATEGY", False))

    def set_use_failover_strategy(self, enabled: bool) -> None:
        """Enable or disable the failover strategy usage."""
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

        if self._state_provider and hasattr(
            self._state_provider, "functional_backends"
        ):
            backends = self._state_provider.functional_backends
            return _normalize_backends(backends)
        local_backends = self._local_state.get("functional_backends", [])
        return _normalize_backends(local_backends)

    def set_functional_backends(self, backends: list[str]) -> None:
        """Set list of functional backends."""
        if self._state_provider:
            self._state_provider.functional_backends = backends
        self._local_state["functional_backends"] = backends

    def get_backend_type(self) -> str | None:
        """Get current backend type."""
        if self._state_provider and hasattr(self._state_provider, "backend_type"):
            backend_type = self._state_provider.backend_type
            return backend_type if isinstance(backend_type, str) else None
        local_backend_type = self._local_state.get("backend_type")
        return local_backend_type if isinstance(local_backend_type, str) else None

    def set_backend_type(self, backend_type: str | None) -> None:
        """Set current backend type."""
        if self._state_provider:
            self._state_provider.backend_type = backend_type
        self._local_state["backend_type"] = backend_type

    def get_backend(self) -> Any:
        """Get current backend instance."""
        if self._state_provider and hasattr(self._state_provider, "backend"):
            return self._state_provider.backend
        return self._local_state.get("backend")

    def set_backend(self, backend: Any) -> None:
        """Set current backend instance."""
        if self._state_provider:
            self._state_provider.backend = backend
        self._local_state["backend"] = backend

    def get_model_defaults(self) -> dict[str, Any]:
        """Get model defaults."""
        if self._state_provider and hasattr(self._state_provider, "model_defaults"):
            defaults = self._state_provider.model_defaults
            return defaults if isinstance(defaults, dict) else {}
        local_defaults = self._local_state.get("model_defaults", {})
        return local_defaults if isinstance(local_defaults, dict) else {}

    def set_model_defaults(self, defaults: dict[str, Any]) -> None:
        """Set model defaults."""
        if self._state_provider:
            self._state_provider.model_defaults = defaults
        self._local_state["model_defaults"] = defaults

    def get_failover_routes(self) -> list[dict[str, Any]] | None:
        """Get failover routes."""
        if self._state_provider and hasattr(self._state_provider, "failover_routes"):
            routes = self._state_provider.failover_routes
            if isinstance(routes, dict):
                return list(routes.values()) if routes else None
            elif isinstance(routes, list):
                return routes
        local_routes = self._local_state.get("failover_routes")
        if isinstance(local_routes, dict):
            return list(local_routes.values()) if local_routes else None
        elif isinstance(local_routes, list):
            return local_routes
        return None

    def set_failover_route(self, name: str, route_config: dict[str, Any]) -> None:
        """Set a failover route."""
        if self._state_provider:
            if not hasattr(self._state_provider, "failover_routes"):
                self._state_provider.failover_routes = {}
            self._state_provider.failover_routes[name] = route_config
        else:
            if "failover_routes" not in self._local_state:
                self._local_state["failover_routes"] = {}
            self._local_state["failover_routes"][name] = route_config

    def set_failover_routes(self, routes: list[dict[str, Any]]) -> None:
        """Set multiple failover routes."""
        if self._state_provider:
            self._state_provider.failover_routes = {}
            for route in routes:
                if isinstance(route, dict) and "name" in route:
                    name = route["name"]
                    route_config = {k: v for k, v in route.items() if k != "name"}
                    self._state_provider.failover_routes[name] = route_config
        else:
            self._local_state["failover_routes"] = {}
            for route in routes:
                if isinstance(route, dict) and "name" in route:
                    name = route["name"]
                    route_config = {k: v for k, v in route.items() if k != "name"}
                    self._local_state["failover_routes"][name] = route_config
