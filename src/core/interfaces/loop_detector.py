from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LoopDetectionResult:
    """Result of a loop detection check."""

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
    """Interface for loop detection operations.

    This interface defines the contract for components that detect
    repetitive patterns in LLM responses, particularly in tool calls.

    Notes for implementers:
    - Only check_for_loops must be implemented.
    - register_tool_call and clear_history have sensible no-op defaults to
      ease testing and mocking.
    """

    @abstractmethod
    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        """Check if the given content contains repetitive patterns.

        Args:
            content: The content to check for loops

        Returns:
            LoopDetectionResult with loop detection information
        """

    async def register_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> None:
        """Register a tool call for future loop detection.

        Default is a no-op to simplify tests.
        """
        return None

    async def clear_history(self) -> None:
        """Clear all recorded history.

        Default is a no-op to simplify tests.
        """
        return None

    @abstractmethod
    async def configure(
        self,
        min_pattern_length: int = 100,
        max_pattern_length: int = 8000,
        min_repetitions: int = 2,
    ) -> None:
        """Configure the loop detector parameters.

        Args:
            min_pattern_length: Minimum length of pattern to detect
            max_pattern_length: Maximum length of pattern to detect
            min_repetitions: Minimum number of repetitions to consider a loop
        """
