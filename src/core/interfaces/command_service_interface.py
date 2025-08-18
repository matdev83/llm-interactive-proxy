from abc import ABC, abstractmethod
from typing import Any

from src.core.domain.processed_result import ProcessedResult


class ICommandService(ABC):
    @abstractmethod
    async def process_commands(
        self, messages: list[Any], session_id: str
    ) -> ProcessedResult:
        pass

    @abstractmethod
    async def register_command(self, command_name: str, command_handler: Any) -> None:
        pass
