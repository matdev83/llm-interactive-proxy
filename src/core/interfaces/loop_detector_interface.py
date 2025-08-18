from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LoopDetectionResult:
    def __init__(
        self,
        has_loop: bool,
        pattern: str | None = None,
        repetitions: int = 0,
        details: dict[str, Any] | None = None,
        modified_content: str | None = None,
    ):
        self.has_loop = has_loop
        self.pattern = pattern
        self.repetitions = repetitions
        self.details = details or {}
        self.modified_content = modified_content


class ILoopDetector(ABC):
    @abstractmethod
    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        pass

    async def register_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> None:
        return None

    async def clear_history(self) -> None:
        return None

    @abstractmethod
    async def configure(
        self,
        min_pattern_length: int = 100,
        max_pattern_length: int = 8000,
        min_repetitions: int = 2,
    ) -> None:
        pass
