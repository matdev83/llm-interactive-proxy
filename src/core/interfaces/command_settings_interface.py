"""
Interface for command settings services.

This module defines interfaces for accessing and modifying command-related settings
that were previously stored in app.state but should be moved to proper DI services.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ICommandSettingsService(ABC):
    """Interface for services that handle command-related settings.

    This service provides access to global command settings like the command prefix
    and API key redaction settings, decoupled from FastAPI app.state.
    """

    @property
    @abstractmethod
    def command_prefix(self) -> str:
        """Get the current command prefix."""

    @command_prefix.setter
    @abstractmethod
    def command_prefix(self, value: str) -> None:
        """Set the command prefix.

        Args:
            value: The new command prefix
        """

    @property
    @abstractmethod
    def api_key_redaction_enabled(self) -> bool:
        """Get whether API key redaction is enabled."""

    @api_key_redaction_enabled.setter
    @abstractmethod
    def api_key_redaction_enabled(self, value: bool) -> None:
        """Set whether API key redaction is enabled.

        Args:
            value: Whether to enable API key redaction
        """

    @abstractmethod
    def reset_to_defaults(self) -> None:
        """Reset all settings to their default values."""
