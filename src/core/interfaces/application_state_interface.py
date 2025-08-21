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
    def get_failover_routes(self) -> list[dict[str, Any]] | None:
        """Get failover routes.

        Returns:
            A list of failover routes, or None if not set
        """

    @abstractmethod
    def set_failover_routes(self, routes: list[dict[str, Any]]) -> None:
        """Set failover routes.

        Args:
            routes: The failover routes
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