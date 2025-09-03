"""
Test-friendly version of StateAccessProxy that allows critical test attributes.

This module provides a modified version of StateAccessProxy that allows
access to critical attributes needed by tests while still enforcing
security boundaries for other attributes.
"""

from __future__ import annotations

from typing import Any

from src.core.services.secure_state_service import StateAccessProxy


class TestStateAccessProxy(StateAccessProxy):
    """
    Test-friendly proxy that allows access to critical test attributes.

    This version of StateAccessProxy allows direct access to certain
    attributes that are critical for testing, such as service_provider.
    """

    def __init__(
        self,
        target_object: Any,
        allowed_interfaces: list[type],
        allowed_attributes: set[str] | None = None,
    ):
        """
        Initialize the test-friendly proxy.

        Args:
            target_object: The object to proxy
            allowed_interfaces: List of interfaces that are allowed to access this object
            allowed_attributes: Set of attribute names that are always allowed
        """
        super().__init__(target_object, allowed_interfaces)
        self._allowed_attributes = allowed_attributes or {
            # Critical attributes for tests
            "service_provider",
            "app_config",
            "command_prefix",
            "backend_type",
            "disable_interactive_commands",
            "api_key_redaction_enabled",
            "functional_backends",
            "httpx_client",
            # Backend-related attributes
            "openrouter_backend",
            "openai_backend",
            "anthropic_backend",
            "gemini_backend",
            "gemini_cli_direct_backend",
            "rate_limits",
            "session_manager",
            "tool_loop_config",
            "client_api_key",
            "disable_auth",
        }

    def __getattr__(self, name: str) -> Any:
        """
        Intercept attribute access and allow critical test attributes.

        Args:
            name: Name of the attribute to access

        Returns:
            The attribute value

        Raises:
            StateAccessViolationError: If the access is not allowed
        """
        # Allow access to test-critical attributes
        if name in self._allowed_attributes:
            return getattr(self._target, name)

        # For other attributes, use the standard security checks
        return super().__getattr__(name)

    def __setattr__(self, name: str, value: Any) -> None:
        """
        Intercept attribute setting and allow critical test attributes.

        Args:
            name: Name of the attribute to set
            value: Value to set

        Raises:
            StateAccessViolationError: If the access is not allowed
        """
        # Allow setting private attributes on the proxy itself
        if name.startswith("_"):
            # Need to call parent of parent class to avoid infinite recursion
            object.__setattr__(self, name, value)
            return

        # Allow setting test-critical attributes
        if name in self._allowed_attributes:
            setattr(self._target, name, value)
            return

        # For other attributes, use the standard security checks
        super().__setattr__(name, value)
