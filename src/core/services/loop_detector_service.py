from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.loop_detection.event import LoopDetectionEvent

from src.core.interfaces.loop_detector_interface import (
    ILoopDetector,
    LoopDetectionResult,
)
from src.loop_detection.config import LoopDetectionConfig
from src.loop_detection.detector import LoopDetector as InternalLoopDetector

logger = logging.getLogger(__name__)


class LoopDetector(ILoopDetector):
    def __init__(
        self,
        min_pattern_length: int = 50,
        max_pattern_length: int = 500,
        min_repetitions: int = 2,
        max_samples: int = 20,
    ):
        self._min_pattern_length = min_pattern_length
        self._max_pattern_length = max_pattern_length
        self._min_repetitions = min_repetitions
        self._max_samples = max_samples
        self._detector = self._create_internal_detector()

    def _create_internal_detector(self) -> InternalLoopDetector:
        """Create a configured instance of the internal loop detector."""

        config = LoopDetectionConfig(
            max_pattern_length=self._max_pattern_length,
            content_loop_threshold=self._min_repetitions,
        )

        return InternalLoopDetector(config=config)

    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        def _as_int(value: Any, default: int) -> int:
            try:
                if isinstance(value, int):
                    return value
                if isinstance(value, dict):
                    for k in (
                        "min_pattern_length",
                        "max_pattern_length",
                        "min_repetitions",
                        "value",
                    ):
                        if k in value and isinstance(value[k], int):
                            return int(value[k])
                for attr in (
                    "min_pattern_length",
                    "max_pattern_length",
                    "min_repetitions",
                    "value",
                ):
                    if hasattr(value, attr):
                        v = getattr(value, attr)
                        if isinstance(v, int):
                            return int(v)
                return int(value)
            except (TypeError, ValueError):
                return default

        min_len = _as_int(self._min_pattern_length, 50)

        if not content or len(content) < min_len * 2:
            return LoopDetectionResult(has_loop=False)

        try:
            # Reset detector state to ensure each check is independent
            self._detector.reset()
            result = await self._detector.check_for_loops(content)
            if result.has_loop and logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Loop detected: %s repetitions of pattern (length %s)",
                    result.repetitions,
                    len(result.pattern) if result.pattern else 0,
                )
            return result

        except (TypeError, ValueError, AttributeError, IndexError) as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error detecting loops: {e}", exc_info=True)
            return LoopDetectionResult(has_loop=False, details={"error": str(e)})

    async def configure(
        self,
        min_pattern_length: int = 100,
        max_pattern_length: int = 8000,
        min_repetitions: int = 2,
    ) -> None:
        self._min_pattern_length = min_pattern_length
        self._max_pattern_length = max_pattern_length
        self._min_repetitions = min_repetitions
        self._detector.update_config(
            LoopDetectionConfig(
                max_pattern_length=self._max_pattern_length,
                content_loop_threshold=self._min_repetitions,
            )
        )

    async def register_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> None:
        return None

    async def clear_history(self) -> None:
        self._detector.reset()

    def is_enabled(self) -> bool:
        """
        Checks if loop detection is currently enabled.

        Returns:
            True if enabled, False otherwise.
        """
        return self._detector.is_enabled()

    def process_chunk(self, chunk: str) -> LoopDetectionEvent | None:
        """
        Processes a single chunk of text for loop detection.

        Args:
            chunk: The text chunk to process.

        Returns:
            A LoopDetectionEvent if a loop is detected, otherwise None.
        """
        return self._detector.process_chunk(chunk)

    def reset(self) -> None:
        """
        Resets the internal state of the loop detector.
        This should be called before processing a new sequence of chunks.
        """
        self._detector.reset()

    def get_loop_history(self) -> list[LoopDetectionEvent]:
        """
        Retrieves the history of detected loops.

        Returns:
            A list of historical loop detection data.
        """
        return self._detector.get_loop_history()

    def get_current_state(self) -> dict[str, Any]:
        """
        Retrieves the current internal state of the loop detector.

        Returns:
            A dictionary representing the current state.
        """
        state = self._detector.get_current_state()
        state.update(
            {
                "min_pattern_length": self._min_pattern_length,
                "max_pattern_length": self._max_pattern_length,
                "min_repetitions": self._min_repetitions,
            }
        )
        return state
