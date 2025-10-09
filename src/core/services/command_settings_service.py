"""
Implementation of the command settings service.

This module provides a concrete implementation of the ICommandSettingsService
interface for managing command-related settings.
"""

from __future__ import annotations

import logging

from src.core.interfaces.command_settings_interface import ICommandSettingsService

logger = logging.getLogger(__name__)


class CommandSettingsService(ICommandSettingsService):
    """Service for managing command settings.

    This implementation provides a central place for storing and accessing
    command-related settings that were previously stored directly in app.state.
    """

    def __init__(
        self,
        default_command_prefix: str = "!/",
        default_api_key_redaction: bool = True,
        default_disable_interactive_commands: bool = False,
    ) -> None:
        """Initialize the command settings service.

        Args:
            default_command_prefix: The default command prefix
            default_api_key_redaction: The default API key redaction setting
        """
        self._command_prefix = default_command_prefix
        self._api_key_redaction_enabled = default_api_key_redaction
        self._disable_interactive_commands = default_disable_interactive_commands
        self._default_command_prefix = default_command_prefix
        self._default_api_key_redaction = default_api_key_redaction
        self._default_disable_interactive_commands = (
            default_disable_interactive_commands
        )

    @property
    def command_prefix(self) -> str:
        """Get the current command prefix."""
        return self._command_prefix

    @command_prefix.setter
    def command_prefix(self, value: str) -> None:
        """Set the command prefix.

        Args:
            value: The new command prefix
        """
        if not value:
            logger.warning("Attempted to set empty command prefix, ignoring")
            return

        self._command_prefix = value
        logger.debug(f"Command prefix set to '{value}'")

    @property
    def api_key_redaction_enabled(self) -> bool:
        """Get whether API key redaction is enabled."""
        return self._api_key_redaction_enabled

    @api_key_redaction_enabled.setter
    def api_key_redaction_enabled(self, value: bool) -> None:
        """Set whether API key redaction is enabled.

        Args:
            value: Whether to enable API key redaction
        """
        self._api_key_redaction_enabled = value
        logger.debug(f"API key redaction {'enabled' if value else 'disabled'}")

    @property
    def disable_interactive_commands(self) -> bool:
        """Get whether interactive commands are disabled."""
        return self._disable_interactive_commands

    @disable_interactive_commands.setter
    def disable_interactive_commands(self, value: bool) -> None:
        """Set whether interactive commands are disabled."""
        self.set_disable_interactive_commands(value)

    def get_command_prefix(self) -> str:
        """Compatibility getter for legacy command settings access."""
        return self._command_prefix

    def get_api_key_redaction_enabled(self) -> bool:
        """Compatibility getter for legacy command settings access."""
        return self._api_key_redaction_enabled

    def get_disable_interactive_commands(self) -> bool:
        """Compatibility getter for legacy command settings access."""
        return self._disable_interactive_commands

    def set_disable_interactive_commands(self, disabled: bool) -> None:
        """Update disable-interactive-commands flag for compatibility users."""
        self._disable_interactive_commands = bool(disabled)

    def reset_to_defaults(self) -> None:
        """Reset all settings to their default values."""
        self._command_prefix = self._default_command_prefix
        self._api_key_redaction_enabled = self._default_api_key_redaction
        self._disable_interactive_commands = self._default_disable_interactive_commands
        logger.debug("Command settings reset to defaults")


# Legacy singleton access removed. Use DI to resolve CommandSettingsService.
