"""
Application settings interface.

This module defines the interface for accessing application-wide settings.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IAppSettings(ABC):
    """Interface for accessing application-wide settings."""

    @abstractmethod
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting by key.

        Args:
            key: The setting key
            default: The default value to return if the setting is not found

        Returns:
            The setting value, or the default value if the setting is not found
        """

    @abstractmethod
    def set_setting(self, key: str, value: Any) -> None:
        """Set a setting by key.

        Args:
            key: The setting key
            value: The setting value
        """

    @abstractmethod
    def has_setting(self, key: str) -> bool:
        """Check if a setting exists.

        Args:
            key: The setting key

        Returns:
            True if the setting exists, False otherwise
        """

    @abstractmethod
    def get_all_settings(self) -> dict[str, Any]:
        """Get all settings.

        Returns:
            A dictionary containing all settings
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
    def get_command_prefix(self) -> str:
        """Get the command prefix.

        Returns:
            The command prefix
        """

    @abstractmethod
    def set_command_prefix(self, prefix: str) -> None:
        """Set the command prefix.

        Args:
            prefix: The command prefix
        """

    @abstractmethod
    def get_redact_api_keys(self) -> bool:
        """Get whether API keys should be redacted.

        Returns:
            True if API keys should be redacted, False otherwise
        """

    @abstractmethod
    def set_redact_api_keys(self, redact: bool) -> None:
        """Set whether API keys should be redacted.

        Args:
            redact: Whether API keys should be redacted
        """

    @abstractmethod
    def get_disable_interactive_commands(self) -> bool:
        """Get whether interactive commands are disabled.

        Returns:
            True if interactive commands are disabled, False otherwise
        """

    @abstractmethod
    def set_disable_interactive_commands(self, disable: bool) -> None:
        """Set whether interactive commands are disabled.

        Args:
            disable: Whether interactive commands are disabled
        """
