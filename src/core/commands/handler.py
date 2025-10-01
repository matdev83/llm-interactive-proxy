"""
Defines the interface for command handlers.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from src.core.commands.command import Command
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session

if TYPE_CHECKING:
    from src.core.interfaces.command_service_interface import ICommandService


class ICommandHandler(ABC):
    """
    Interface for a command handler.
    """

    def __init__(
        self,
        command_service: "ICommandService | None" = None,
        secure_state_access: Any = None,
        secure_state_modification: Any = None,
    ) -> None:
        self._command_service = command_service
        self._secure_state_access = secure_state_access
        self._secure_state_modification = secure_state_modification

    @property
    @abstractmethod
    def command_name(self) -> str:
        """The name of the command."""

    @property
    @abstractmethod
    def description(self) -> str:
        """A short description of the command."""

    @property
    @abstractmethod
    def format(self) -> str:
        """The format of the command."""

    @property
    @abstractmethod
    def examples(self) -> list[str]:
        """A list of examples of how to use the command."""

    @abstractmethod
    async def handle(self, command: Command, session: Session) -> CommandResult:
        """
        Handles the command.

        Args:
            command: The command to handle.
            session: The user session.

        Returns:
            A CommandResult object with the result of the command.
        """
