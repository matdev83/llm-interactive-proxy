from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.command_results import CommandResult


class BaseCommand(ABC):
    """
    The base class for all commands.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The name of the command."""
        raise NotImplementedError

    @abstractmethod
    async def execute(self, *args: Any, **kwargs: Any) -> CommandResult:
        """
        Executes the command.

        Returns:
            A CommandResult object.
        """
        raise NotImplementedError
