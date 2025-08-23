"""
Secure state service that enforces proper access patterns.

This service acts as a gatekeeper for all state access, ensuring that
only authorized operations are performed through proper interfaces.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
    StateAccessViolationError,
)

logger = logging.getLogger(__name__)


class SecureStateService(ISecureStateAccess, ISecureStateModification):
    """Secure state service that enforces proper access patterns."""

    def __init__(self, application_state: IApplicationState):
        """Initialize with application state dependency.

        Args:
            application_state: The application state service to use
        """
        self._application_state = application_state
        self._access_log: list[dict[str, Any]] = []

    # Secure read access methods
    def get_command_prefix(self) -> str | None:
        """Get the command prefix through secure access."""
        self._log_access("get_command_prefix", "read")
        return self._application_state.get_command_prefix()

    def get_api_key_redaction_enabled(self) -> bool:
        """Get API key redaction setting through secure access."""
        self._log_access("get_api_key_redaction_enabled", "read")
        return self._application_state.get_api_key_redaction_enabled()

    def get_disable_interactive_commands(self) -> bool:
        """Get interactive commands disabled setting through secure access."""
        self._log_access("get_disable_interactive_commands", "read")
        return self._application_state.get_disable_interactive_commands()

    def get_failover_routes(self) -> list[dict[str, Any]] | None:
        """Get failover routes through secure access."""
        self._log_access("get_failover_routes", "read")
        return self._application_state.get_failover_routes()

    # Secure modification methods with validation
    def update_command_prefix(self, prefix: str) -> None:
        """Update command prefix with validation."""
        if not isinstance(prefix, str):
            raise StateAccessViolationError(
                "Command prefix must be a string",
                "ISecureStateModification.update_command_prefix",
            )

        if not prefix.strip():
            raise StateAccessViolationError(
                "Command prefix cannot be empty",
                "ISecureStateModification.update_command_prefix",
            )

        self._log_access("update_command_prefix", "write", {"prefix": prefix})
        self._application_state.set_command_prefix(prefix)

    def update_api_key_redaction(self, enabled: bool) -> None:
        """Update API key redaction with validation."""
        if not isinstance(enabled, bool):
            raise StateAccessViolationError(
                "API key redaction setting must be a boolean",
                "ISecureStateModification.update_api_key_redaction",
            )

        self._log_access("update_api_key_redaction", "write", {"enabled": enabled})
        self._application_state.set_api_key_redaction_enabled(enabled)

    def update_interactive_commands(self, disabled: bool) -> None:
        """Update interactive commands setting with validation."""
        if not isinstance(disabled, bool):
            raise StateAccessViolationError(
                "Interactive commands setting must be a boolean",
                "ISecureStateModification.update_interactive_commands",
            )

        self._log_access("update_interactive_commands", "write", {"disabled": disabled})
        self._application_state.set_disable_interactive_commands(disabled)

    def update_failover_routes(self, routes: list[dict[str, Any]]) -> None:
        """Update failover routes with validation."""
        if not isinstance(routes, list):
            raise StateAccessViolationError(
                "Failover routes must be a list",
                "ISecureStateModification.update_failover_routes",
            )

        # Validate route structure
        for i, route in enumerate(routes):
            if not isinstance(route, dict):
                raise StateAccessViolationError(
                    f"Route {i} must be a dictionary",
                    "ISecureStateModification.update_failover_routes",
                )

            if "name" not in route:
                raise StateAccessViolationError(
                    f"Route {i} must have a 'name' field",
                    "ISecureStateModification.update_failover_routes",
                )

        self._log_access(
            "update_failover_routes", "write", {"routes_count": len(routes)}
        )
        self._application_state.set_failover_routes(routes)

    def _log_access(
        self, operation: str, access_type: str, data: dict[str, Any] | None = None
    ) -> None:
        """Log state access for auditing purposes."""
        log_entry = {
            "operation": operation,
            "access_type": access_type,
            "timestamp": __import__("time").time(),
            "data": data or {},
        }
        self._access_log.append(log_entry)
        logger.debug(f"State access: {operation} ({access_type})")

    def get_access_log(self) -> list[dict[str, Any]]:
        """Get the access log for auditing."""
        return self._access_log.copy()


class StateAccessProxy:
    """Proxy that prevents direct state access and enforces DI usage."""

    def __init__(self, target_object: Any, allowed_interfaces: list[type]):
        """Initialize the proxy.

        Args:
            target_object: The object to proxy
            allowed_interfaces: List of interfaces that are allowed to access this object
        """
        self._target = target_object
        self._allowed_interfaces = allowed_interfaces

    def __getattr__(self, name: str) -> Any:
        """Intercept attribute access and enforce interface usage."""
        # Check if the caller is using an allowed interface
        import inspect

        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_locals = frame.f_back.f_locals

            # Check if 'self' in caller is an instance of allowed interfaces
            caller_self = caller_locals.get("self")
            if caller_self:
                for interface in self._allowed_interfaces:
                    if isinstance(caller_self, interface):
                        return getattr(self._target, name)

        # If we get here, the access is not through an allowed interface
        raise StateAccessViolationError(
            f"Direct access to '{name}' is not allowed. "
            f"Use one of these interfaces: {[i.__name__ for i in self._allowed_interfaces]}",
            f"Use dependency injection with {self._allowed_interfaces[0].__name__}",
        )

    def __setattr__(self, name: str, value: Any) -> None:
        """Intercept attribute setting and enforce interface usage."""
        if name.startswith("_"):
            # Allow setting private attributes on the proxy itself
            super().__setattr__(name, value)
            return

        # For public attributes, enforce interface usage
        import inspect

        frame = inspect.currentframe()
        if frame and frame.f_back:
            caller_locals = frame.f_back.f_locals
            caller_self = caller_locals.get("self")

            if caller_self:
                for interface in self._allowed_interfaces:
                    if isinstance(caller_self, interface):
                        setattr(self._target, name, value)
                        return

        raise StateAccessViolationError(
            f"Direct setting of '{name}' is not allowed. "
            f"Use one of these interfaces: {[i.__name__ for i in self._allowed_interfaces]}",
            f"Use dependency injection with {self._allowed_interfaces[0].__name__}",
        )
