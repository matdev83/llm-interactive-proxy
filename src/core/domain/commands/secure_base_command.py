"""
Secure base command that enforces proper dependency injection.

This base class ensures that domain commands cannot access state directly
and must use proper DI patterns.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
from typing import Any, final

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
    StateAccessViolationError,
)


class SecureCommandBase(BaseCommand):
    """Base class for domain commands that enforces secure state access."""

    def __init__(
        self,
        state_reader: ISecureStateAccess | None = None,
        state_modifier: ISecureStateModification | None = None,
    ):
        """Initialize the command with optional state services.

        Args:
            state_reader: Service for reading state securely
            state_modifier: Service for modifying state securely
        """
        self._state_reader = state_reader
        self._state_modifier = state_modifier
        self._execution_count = 0

    @property
    @abstractmethod
    def name(self) -> str:
        """Command name."""

    @property
    @abstractmethod
    def format(self) -> str:
        """Command format string."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Command description."""

    @property
    def examples(self) -> list[str]:
        """Command examples (optional)."""
        return []

    @abstractmethod
    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Execute the command.

        Args:
            args: Command arguments
            session: Current session
            context: Optional context (should not be used for state access)

        Returns:
            Command result
        """

    def get_state_setting(self, setting_name: str) -> Any:
        """Get a setting value from the secure state.

        Args:
            setting_name: Name of the setting to retrieve

        Returns:
            The value of the setting

        Raises:
            StateAccessViolationError: If the setting is not accessible
        """
        if not self._state_reader:
            raise StateAccessViolationError(
                f"Cannot read state setting '{setting_name}' - no state reader injected",
                "Inject ISecureStateAccess through constructor",
            )

        # Map setting names to secure methods
        setting_methods = {
            "command_prefix": self._state_reader.get_command_prefix,
            "api_key_redaction_enabled": self._state_reader.get_api_key_redaction_enabled,
            "disable_interactive_commands": self._state_reader.get_disable_interactive_commands,
            "failover_routes": self._state_reader.get_failover_routes,
        }

        method = setting_methods.get(setting_name)
        if not method:
            raise StateAccessViolationError(
                f"Unknown state setting: {setting_name}",
                "Use one of: " + ", ".join(setting_methods.keys()),
            )

        return method()

    def update_state_setting(self, setting_name: str, value: Any) -> None:
        """Update a setting value in the secure state.

        Args:
            setting_name: Name of the setting to update
            value: New value for the setting

        Raises:
            StateAccessViolationError: If the setting is not modifiable
        """
        if not self._state_modifier:
            raise StateAccessViolationError(
                f"Cannot update state setting '{setting_name}' - no state modifier injected",
                "Inject ISecureStateModification through constructor",
            )

        # Map setting names to secure methods
        setting_methods = {
            "command_prefix": self._state_modifier.update_command_prefix,
            "api_key_redaction_enabled": self._state_modifier.update_api_key_redaction,
            "disable_interactive_commands": self._state_modifier.update_interactive_commands,
            "failover_routes": self._state_modifier.update_failover_routes,
        }

        method = setting_methods.get(setting_name)
        if not method:
            raise StateAccessViolationError(
                f"Unknown state setting: {setting_name}",
                "Use one of: " + ", ".join(setting_methods.keys()),
            )

        return method(value)  # type: ignore

    @final
    def _increment_execution_count(self) -> None:
        """Track command execution for monitoring."""
        self._execution_count += 1

    @property
    def execution_count(self) -> int:
        """Get the number of times this command has been executed."""
        return self._execution_count


class StatelessCommandBase(SecureCommandBase):
    """Base class for commands that don't need state access."""

    def __init__(self) -> None:
        """Initialize without state services."""
        super().__init__(state_reader=None, state_modifier=None)

    def get_state_setting(self, setting_name: str) -> Any:
        """Override to prevent state access in stateless commands."""
        raise StateAccessViolationError(
            f"Stateless command {self.name} cannot access state setting '{setting_name}'",
            "Use StatefulCommandBase if state access is needed",
        )

    def update_state_setting(self, setting_name: str, value: Any) -> None:
        """Override to prevent state modification in stateless commands."""
        raise StateAccessViolationError(
            f"Stateless command {self.name} cannot modify state setting '{setting_name}'",
            "Use StatefulCommandBase if state modification is needed",
        )


class StatefulCommandBase(SecureCommandBase):
    """Base class for commands that need state access."""

    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification | None = None,
    ):
        """Initialize with required state services.

        Args:
            state_reader: Required service for reading state
            state_modifier: Optional service for modifying state
        """
        if not state_reader:
            raise StateAccessViolationError(
                "StatefulCommandBase requires ISecureStateAccess to be injected",
                "Inject ISecureStateAccess through constructor",
            )

        super().__init__(state_reader=state_reader, state_modifier=state_modifier)


# Factory function to create commands with proper DI
def create_secure_command(
    command_class: type[SecureCommandBase],
    state_reader: ISecureStateAccess | None = None,
    state_modifier: ISecureStateModification | None = None,
) -> SecureCommandBase:
    """Factory function to create commands with proper dependency injection.

    Args:
        command_class: The command class to instantiate
        state_reader: State reading service
        state_modifier: State modification service

    Returns:
        Configured command instance

    Raises:
        StateAccessViolationError: If required dependencies are missing
    """
    # Check if the command class requires state services
    if issubclass(command_class, StatefulCommandBase):
        if not state_reader:
            raise StateAccessViolationError(
                f"{command_class.__name__} requires ISecureStateAccess",
                "Provide state_reader parameter",
            )
        return command_class(state_reader=state_reader, state_modifier=state_modifier)

    elif issubclass(command_class, StatelessCommandBase):
        return command_class()

    else:
        # Generic SecureCommandBase
        return command_class(state_reader=state_reader, state_modifier=state_modifier)
