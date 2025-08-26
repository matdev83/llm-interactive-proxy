from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.loop_detection.event import LoopDetectionEvent

from dataclasses import dataclass


@dataclass
class LoopDetectionResult:
    """Result of a loop detection check."""

    has_loop: bool
    pattern: str | None = None
    repetitions: int | None = None
    details: dict[str, Any] | None = None


class ILoopDetector(abc.ABC):
    """
    Interface for a service that detects repetitive patterns or "loops" in text.
    """

    @abc.abstractmethod
    def is_enabled(self) -> bool:
        """
        Checks if loop detection is currently enabled.

        Returns:
            True if enabled, False otherwise.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def process_chunk(self, chunk: str) -> LoopDetectionEvent | None:
        """
        Processes a single chunk of text for loop detection.

        Args:
            chunk: The text chunk to process.

        Returns:
            A LoopDetectionEvent if a loop is detected, otherwise None.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def reset(self) -> None:
        """
        Resets the internal state of the loop detector.
        This should be called before processing a new sequence of chunks.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_loop_history(self) -> list[LoopDetectionEvent]:
        """
        Retrieves the history of detected loops.

        Returns:
            A list of historical loop detection data.
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_current_state(self) -> dict[str, Any]:
        """
        Retrieves the current internal state of the loop detector.

        Returns:
            A dictionary representing the current state.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        """
        Checks for repetitive patterns (loops) in the given content.

        Args:
            content: The content string to check for loops.

        Returns:
            A LoopDetectionResult indicating whether a loop was found and details.
        """
        raise NotImplementedError
