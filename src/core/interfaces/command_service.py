from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.processed_result import ProcessedResult


class ICommandService(ABC):
    """Interface for command processing operations.

    This interface defines the contract for components that handle command
    parsing and execution within user messages.
    """

    @abstractmethod
    async def process_commands(
        self, messages: list[Any], session_id: str
    ) -> ProcessedResult:
        """Process any commands in the messages list.

        Examines the messages for command patterns, executes any commands found,
        and returns the potentially modified message list along with results.

        Args:
            messages: List of message objects to process
            session_id: The session ID associated with this request

        Returns:
            A ProcessedResult object containing the processed messages and command results
        """

    @abstractmethod
    async def register_command(self, command_name: str, command_handler: Any) -> None:
        """Register a new command handler.

        Args:
            command_name: The name of the command to register
            command_handler: The handler object or function for the command
        """
