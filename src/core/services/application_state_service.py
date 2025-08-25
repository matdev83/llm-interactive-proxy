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

    def get_failover_routes(self) -> list[dict[str, Any]] | None:
        """Get failover routes."""
        if self._state_provider and hasattr(self._state_provider, "failover_routes"):
            routes = self._state_provider.failover_routes
            return routes if isinstance(routes, list) else None
        local_routes = self._local_state.get("failover_routes")
        return local_routes if isinstance(local_routes, list) else None

    def set_failover_routes(self, routes: list[dict[str, Any]]) -> None:
        """Set failover routes."""
        if self._state_provider:
            self._state_provider.failover_routes = routes
        self._local_state["failover_routes"] = routes

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


# Global instance for backward compatibility
_default_instance: ApplicationStateService | None = None


def get_default_application_state() -> ApplicationStateService:
    """Get the default application state service instance.

    Returns:
        The default application state service instance
    """
    global _default_instance
    if _default_instance is None:
        _default_instance = ApplicationStateService()
    return _default_instance


def set_default_application_state(instance: ApplicationStateService) -> None:
    """Set the default application state service instance.

    Args:
        instance: The application state service instance
    """
    global _default_instance
    _default_instance = instance
