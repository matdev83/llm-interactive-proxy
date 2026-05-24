from abc import ABC, abstractmethod
from typing import Any

from src.core.commands.models import Command, CommandResultWrapper
from src.core.domain.processed_result import ProcessedResult


class ICommandService(ABC):
    @abstractmethod
    async def process_commands(
        self, messages: list[Any], session_id: str
    ) -> ProcessedResult:
        pass

    @abstractmethod
    async def execute_command(
        self, command: Command, session_id: str
    ) -> CommandResultWrapper:
        pass
