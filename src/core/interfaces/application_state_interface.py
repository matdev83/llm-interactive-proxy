"""
Application state interface.

This module defines the interface for managing application-wide state
without coupling to specific web framework implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IApplicationState(ABC):
    """Interface for managing application-wide state."""

    @abstractmethod
    def get_command_prefix(self) -> str | None:
        """Get the command prefix.

        Returns:
            The command prefix, or None if not set
        """

    @abstractmethod
    def set_command_prefix(self, prefix: str) -> None:
        """Set the command prefix.

        Args:
            prefix: The command prefix
        """

    @abstractmethod
    def get_api_key_redaction_enabled(self) -> bool:
        """Get whether API key redaction is enabled.

        Returns:
            True if API key redaction is enabled, False otherwise
        """

    @abstractmethod
    def set_api_key_redaction_enabled(self, enabled: bool) -> None:
        """Set whether API key redaction is enabled.

        Args:
            enabled: Whether API key redaction is enabled
        """

    @abstractmethod
    def get_disable_interactive_commands(self) -> bool:
        """Get whether interactive commands are disabled.

        Returns:
            True if interactive commands are disabled, False otherwise
        """

    @abstractmethod
    def set_disable_interactive_commands(self, disabled: bool) -> None:
        """Set whether interactive commands are disabled.

        Args:
            disabled: Whether interactive commands are disabled
        """

    @abstractmethod
    def get_disable_commands(self) -> bool:
        """Get whether commands are disabled.

        Returns:
            True if commands are disabled, False otherwise
        """

    @abstractmethod
    def set_disable_commands(self, disabled: bool) -> None:
        """Set whether commands are disabled.

        Args:
            disabled: Whether commands are disabled
        """

    @abstractmethod
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a generic setting by key.

        Args:
            key: The setting key
            default: The default value to return if the setting is not found

        Returns:
            The setting value, or the default value if the setting is not found
        """

    @abstractmethod
    def set_setting(self, key: str, value: Any) -> None:
        """Set a generic setting by key.

        Args:
            key: The setting key
            value: The setting value
        """

    @abstractmethod
    def get_use_failover_strategy(self) -> bool:
        """Get whether to use the extracted failover strategy.

        Returns:
            True if the extracted failover strategy should be used, False otherwise
        """

    @abstractmethod
    def set_use_failover_strategy(self, enabled: bool) -> None:
        """Set whether to use the extracted failover strategy.

        Args:
            enabled: Whether the extracted failover strategy should be used
        """

    @abstractmethod
    def get_use_streaming_pipeline(self) -> bool:
        """Get whether to use the streaming pipeline.

        Returns:
            True if the streaming pipeline should be used, False otherwise
        """

    @abstractmethod
    def set_use_streaming_pipeline(self, enabled: bool) -> None:
        """Set whether to use the streaming pipeline.

        Args:
            enabled: Whether the streaming pipeline should be used
        """

    @abstractmethod
    def get_functional_backends(self) -> list[str]:
        """Get list of functional backends.

        Returns:
            List of functional backend names
        """

    @abstractmethod
    def set_functional_backends(self, backends: list[str]) -> None:
        """Set list of functional backends.

        Args:
            backends: List of functional backend names
        """

    @abstractmethod
    def get_backend_type(self) -> str | None:
        """Get current backend type.

        Returns:
            Current backend type or None if not set
        """

    @abstractmethod
    def set_backend_type(self, backend_type: str | None) -> None:
        """Set current backend type.

        Args:
            backend_type: The backend type to set
        """

    @abstractmethod
    def get_backend(self) -> Any:
        """Get current backend instance.

        Returns:
            Current backend instance or None if not set
        """

    @abstractmethod
    def set_backend(self, backend: Any) -> None:
        """Set current backend instance.

        Args:
            backend: The backend instance to set
        """

    @abstractmethod
    def get_model_defaults(self) -> dict[str, Any]:
        """Get model defaults.

        Returns:
            Dictionary of model defaults
        """

    @abstractmethod
    def set_model_defaults(self, defaults: dict[str, Any]) -> None:
        """Set model defaults.

        Args:
            defaults: Dictionary of model defaults
        """

    @abstractmethod
    def get_legacy_backend(self, backend_name: str) -> Any | None:
        """Get legacy backend instance by name.

        Args:
            backend_name: Name of the backend

        Returns:
            Backend instance or None if not found
        """

    @abstractmethod
    def set_legacy_backend(self, backend_name: str, backend_instance: Any) -> None:
        """Set legacy backend instance by name.

        Args:
            backend_name: Name of the backend
            backend_instance: The backend instance
        """

    @abstractmethod
    def get_failover_routes(self) -> list[dict[str, Any]] | None:
        """Get failover routes.

        Returns:
            List of failover routes, or None if not set
        """

    @abstractmethod
    def set_failover_route(self, name: str, route_config: dict[str, Any]) -> None:
        """Set a failover route.

        Args:
            name: Name of the failover route
            route_config: Route configuration
        """

    @abstractmethod
    def set_failover_routes(self, routes: list[dict[str, Any]]) -> None:
        """Set multiple failover routes.

        Args:
            routes: List of failover routes
        """
