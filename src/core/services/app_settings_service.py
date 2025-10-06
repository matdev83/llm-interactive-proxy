"""
Application settings service.

This module provides the implementation of the application settings interface.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from src.core.interfaces.app_settings_interface import IAppSettings

logger = logging.getLogger(__name__)
def _get_strict_services_errors() -> bool:
    """Get strict services errors setting from environment."""
    return os.getenv("STRICT_SERVICES_ERRORS", "false").lower() in (
        "true",
        "1",
        "yes",
    )


class AppSettings(IAppSettings):
    """Implementation of the application settings interface."""

    def __init__(self, app_state: Any = None) -> None:
        """Initialize the application settings.

        Args:
            app_state: Optional application state object
        """
        self._settings: dict[str, Any] = {}
        self._app_state = app_state

        # Initialize settings from app_state if provided
        if app_state is not None:
            self._initialize_from_app_state(app_state)

    def _initialize_from_app_state(self, app_state: Any) -> None:
        """Initialize settings from app_state.

        Args:
            app_state: The application state object
        """
        # Try to extract common settings from app_state
        try:
            # Extract failover routes
            if hasattr(app_state, "failover_routes"):
                self._settings["failover_routes"] = app_state.failover_routes

            # Extract command prefix
            if hasattr(app_state, "command_prefix"):
                self._settings["command_prefix"] = app_state.command_prefix

            # Extract redact API keys
            if hasattr(app_state, "redact_api_keys"):
                self._settings["redact_api_keys"] = app_state.redact_api_keys

            # Extract disable interactive commands
            if hasattr(app_state, "disable_interactive_commands"):
                self._settings["disable_interactive_commands"] = (
                    app_state.disable_interactive_commands
                )
        except Exception as e:
            if _get_strict_services_errors():
                raise
            logger.warning(f"Error initializing settings from app_state: {e}")

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting by key.

        Args:
            key: The setting key
            default: The default value to return if the setting is not found

        Returns:
            The setting value, or the default value if the setting is not found
        """
        # Try to get from settings dict first
        if key in self._settings:
            return self._settings[key]

        # Try to get from app_state if available
        if self._app_state is not None:
            try:
                if hasattr(self._app_state, key):
                    return getattr(self._app_state, key)
            except Exception:
                if _get_strict_services_errors():
                    raise
                # Best-effort fallback when not strict
                return default

        # Return default
        return default

    def set_setting(self, key: str, value: Any) -> None:
        """Set a setting by key.

        Args:
            key: The setting key
            value: The setting value
        """
        # Set in settings dict
        self._settings[key] = value

        # Also set in app_state if available
        if self._app_state is not None:
            try:
                setattr(self._app_state, key, value)
            except Exception as e:
                if _get_strict_services_errors():
                    raise
                logger.warning(f"Error setting {key} in app_state: {e}")

    def has_setting(self, key: str) -> bool:
        """Check if a setting exists.

        Args:
            key: The setting key

        Returns:
            True if the setting exists, False otherwise
        """
        # Check settings dict first
        if key in self._settings:
            return True

        # Check app_state if available
        if self._app_state is not None:
            try:
                return hasattr(self._app_state, key)
            except Exception:
                if _get_strict_services_errors():
                    raise
                return False

        return False

    def get_all_settings(self) -> dict[str, Any]:
        """Get all settings.

        Returns:
            A dictionary containing all settings
        """
        # Start with settings dict
        all_settings = dict(self._settings)

        # Add settings from app_state if available
        if self._app_state is not None:
            try:
                for key in dir(self._app_state):
                    # Skip private attributes and methods
                    if key.startswith("_") or callable(getattr(self._app_state, key)):
                        continue

                    # Add to all_settings if not already present
                    if key not in all_settings:
                        all_settings[key] = getattr(self._app_state, key)
            except Exception as e:
                if _get_strict_services_errors():
                    raise
                logger.warning(f"Error getting all settings from app_state: {e}")

        return all_settings

    def get_failover_routes(self) -> list[dict[str, Any]] | None:
        """Get failover routes.

        Returns:
            A list of failover routes, or None if not set
        """
        routes = self.get_setting("failover_routes")
        if routes is None:
            return None
        # Ensure we return the correct type
        if isinstance(routes, list):
            return routes
        return None

    def set_failover_routes(self, routes: list[dict[str, Any]]) -> None:
        """Set failover routes.

        Args:
            routes: The failover routes
        """
        self.set_setting("failover_routes", routes)

    def get_command_prefix(self) -> str:
        """Get the command prefix.

        Returns:
            The command prefix
        """
        prefix = self.get_setting("command_prefix", "!")
        # Ensure we return a string
        if isinstance(prefix, str):
            return prefix
        return "!"

    def set_command_prefix(self, prefix: str) -> None:
        """Set the command prefix.

        Args:
            prefix: The command prefix
        """
        self.set_setting("command_prefix", prefix)

    def get_redact_api_keys(self) -> bool:
        """Get whether API keys should be redacted.

        Returns:
            True if API keys should be redacted, False otherwise
        """
        redact = self.get_setting("redact_api_keys", True)
        # Ensure we return a boolean
        if isinstance(redact, bool):
            return redact
        return True

    def set_redact_api_keys(self, redact: bool) -> None:
        """Set whether API keys should be redacted.

        Args:
            redact: Whether API keys should be redacted
        """
        self.set_setting("redact_api_keys", redact)

    def get_disable_interactive_commands(self) -> bool:
        """Get whether interactive commands are disabled.

        Returns:
            True if interactive commands are disabled, False otherwise
        """
        disable = self.get_setting("disable_interactive_commands", False)
        # Ensure we return a boolean
        if isinstance(disable, bool):
            return disable
        return False

    def set_disable_interactive_commands(self, disable: bool) -> None:
        """Set whether interactive commands are disabled.

        Args:
            disable: Whether interactive commands are disabled
        """
        self.set_setting("disable_interactive_commands", disable)
