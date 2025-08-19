"""
Implementation of the command settings service.

This module provides a concrete implementation of the ICommandSettingsService
interface for managing command-related settings.
"""

from __future__ import annotations

import logging
from typing import Optional

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
    ) -> None:
        """Initialize the command settings service.
        
        Args:
            default_command_prefix: The default command prefix
            default_api_key_redaction: The default API key redaction setting
        """
        self._command_prefix = default_command_prefix
        self._api_key_redaction_enabled = default_api_key_redaction
        self._default_command_prefix = default_command_prefix
        self._default_api_key_redaction = default_api_key_redaction
    
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
    
    def reset_to_defaults(self) -> None:
        """Reset all settings to their default values."""
        self._command_prefix = self._default_command_prefix
        self._api_key_redaction_enabled = self._default_api_key_redaction
        logger.debug("Command settings reset to defaults")


# Singleton instance for legacy compatibility during transition
# This should be removed once DI is fully implemented
_default_instance: Optional[CommandSettingsService] = None


def get_default_instance() -> CommandSettingsService:
    """Get the default singleton instance of the CommandSettingsService.
    
    This function is provided for legacy compatibility during the transition
    to full dependency injection. New code should use proper DI instead.
    
    Returns:
        The default CommandSettingsService instance
    """
    global _default_instance
    if _default_instance is None:
        _default_instance = CommandSettingsService()
    return _default_instance
