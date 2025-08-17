from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.command_context import CommandContext
from src.core.domain.command_results import CommandResult
from src.core.interfaces.domain_entities import ISessionState

logger = logging.getLogger(__name__)


class CommandHandlerResult:
    """Result of a command handler execution."""

    def __init__(
        self,
        success: bool,
        message: str,
        new_state: ISessionState | None = None,
        additional_data: dict[str, Any] | None = None,
    ):
        """Initialize command handler result.

        Args:
            success: Whether the command executed successfully
            message: Message describing the result
            new_state: Updated session state if the command changes state
            additional_data: Any additional data to include in the result
        """
        self.success = success
        self.message = message
        self.new_state = new_state
        self.additional_data = additional_data or {}


class ICommandHandler(ABC):
    """Interface for command handlers.

    Each command handler is responsible for handling a specific setting or
    configuration option.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the parameter this handler manages."""

    @property
    def aliases(self) -> list[str]:
        """Aliases for the parameter name."""
        return []

    @property
    def description(self) -> str:
        """Description of the parameter."""
        return f"Set {self.name} value"

    @property
    def examples(self) -> list[str]:
        """Examples of using this parameter."""
        return [f"!/set({self.name}=value)"]

    @abstractmethod
    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """

    @abstractmethod
    def handle(
        self,
        param_value: Any,
        current_state: ISessionState,
        context: CommandContext | None = None,
    ) -> CommandHandlerResult:
        """Handle setting the parameter value.

        Args:
            param_value: The value to set
            current_state: The current session state
            context: Optional command context for backward compatibility

        Returns:
            A result containing success/failure status and possibly updated state
        """

    def convert_to_legacy_result(
        self, result: CommandHandlerResult, command_name: str = "set"
    ) -> tuple[bool, str | CommandResult | None, bool]:
        """Convert the result to the format expected by the legacy command system.

        Args:
            result: The command handler result
            command_name: The name of the command

        Returns:
            A tuple in the legacy format (handled, message_or_result, requires_auth)
        """
        if not result.success:
            return (
                True,
                CommandResult(success=False, message=result.message, name=command_name),
                False,
            )
        return True, result.message, False


class BaseCommandHandler(ICommandHandler, ABC):
    """Base implementation of command handler.

    Provides common functionality for command handlers.
    """

    def __init__(self, name: str, aliases: list[str] | None = None):
        """Initialize the base command handler.

        Args:
            name: The name of the parameter this handler manages
            aliases: Optional list of aliases for the parameter name
        """
        self._name = name
        self._aliases = aliases or []

    @property
    def name(self) -> str:
        """The name of the parameter this handler manages."""
        return self._name

    @property
    def aliases(self) -> list[str]:
        """Aliases for the parameter name."""
        return self._aliases

    def can_handle(self, param_name: str) -> bool:
        """Check if this handler can handle the given parameter.

        Args:
            param_name: The parameter name to check

        Returns:
            True if this handler can handle the parameter
        """
        normalized = param_name.lower().replace("_", "-")
        return normalized == self.name.lower() or normalized in [
            a.lower() for a in self.aliases
        ]
