"""
Secure command factory that enforces proper DI for domain commands.

This factory ensures that all commands are created with proper dependencies
and prevents direct state access violations.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from src.core.common.exceptions import CommandCreationError
from src.core.domain.commands.secure_base_command import (
    SecureCommandBase,
    StatefulCommandBase,
    StatelessCommandBase,
)
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
    StateAccessViolationError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SecureCommandBase)


class SecureCommandFactory:
    """Factory for creating domain commands with proper DI enforcement."""

    def __init__(
        self, state_reader: ISecureStateAccess, state_modifier: ISecureStateModification
    ):
        """Initialize the factory with state services.

        Args:
            state_reader: Service for reading state
            state_modifier: Service for modifying state
        """
        self._state_reader = state_reader
        self._state_modifier = state_modifier
        self._created_commands: dict[str, SecureCommandBase] = {}

    def create_command(self, command_class: type[T]) -> T:
        """Create a command with proper dependency injection.

        Args:
            command_class: The command class to create

        Returns:
            Configured command instance

        Raises:
            StateAccessViolationError: If command requirements are not met
        """
        command_name = getattr(command_class, "__name__", str(command_class))

        # Check if we already created this command (singleton pattern)
        if command_name in self._created_commands:
            return self._created_commands[command_name]  # type: ignore

        # Validate command class
        if not issubclass(command_class, SecureCommandBase):
            raise StateAccessViolationError(
                f"Command {command_name} must inherit from SecureCommandBase",
                "Use StatefulCommandBase or StatelessCommandBase",
            )

        # Create command with appropriate dependencies
        try:
            command: T
            if issubclass(command_class, StatefulCommandBase):
                logger.debug(f"Creating stateful command: {command_name}")
                command = command_class(
                    state_reader=self._state_reader, state_modifier=self._state_modifier
                )
            elif issubclass(command_class, StatelessCommandBase):
                logger.debug(f"Creating stateless command: {command_name}")
                command = command_class()
            else:
                # Generic SecureCommandBase
                logger.debug(f"Creating generic secure command: {command_name}")
                command = command_class(
                    state_reader=self._state_reader, state_modifier=self._state_modifier
                )

            # Cache the command
            self._created_commands[command_name] = command

            logger.info(f"Successfully created command: {command_name}")
            return command  # type: ignore

        except StateAccessViolationError:
            raise
        except TypeError as e:
            logger.error(
                f"Type error creating command {command_name}: {e}. Check constructor signature.",
                exc_info=True,
            )
            raise StateAccessViolationError(
                f"Failed to create command {command_name} due to a type error: {e}",
                "Ensure command constructor accepts required dependencies (e.g., state_reader, state_modifier).",
            ) from e
        except Exception as e:
            logger.error(
                f"An unexpected error occurred while creating command {command_name}: {e}",
                exc_info=True,
            )
            raise CommandCreationError(
                message=f"An unexpected error occurred while creating command {command_name}: {e}",
                command_name=command_name,
            ) from e

    def get_created_commands(self) -> dict[str, SecureCommandBase]:
        """Get all commands created by this factory."""
        return self._created_commands.copy()

    def clear_cache(self) -> None:
        """Clear the command cache."""
        self._created_commands.clear()


class LegacyCommandAdapter:  # Deprecated; retained as no-op shim for compatibility
    """Deprecated shim; no longer used. Kept to avoid import errors."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
        logger.warning("LegacyCommandAdapter is deprecated and a no-op.")

    def __getattr__(self, name: str) -> Any:  # pragma: no cover
        raise AttributeError(
            "LegacyCommandAdapter is deprecated; remove usages and migrate to SecureCommandBase"
        )
