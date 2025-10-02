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

        self._config = self._build_config()
        self._detector = self._create_internal_detector()

    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        if not content:
            return LoopDetectionResult(has_loop=False)

        detector = self._detector
        if not detector.is_enabled():
            return LoopDetectionResult(has_loop=False)

        detector.reset()
        detection_event = detector.process_chunk(content)

        if detection_event is None:
            return LoopDetectionResult(has_loop=False)

        logger.warning(
            "Loop detected: %s repetitions of pattern length %s",
            detection_event.repetition_count,
            len(detection_event.pattern),
        )

        return LoopDetectionResult(
            has_loop=True,
            pattern=detection_event.pattern,
            repetitions=detection_event.repetition_count,
            details={
                "pattern_length": len(detection_event.pattern),
                "total_repeated_chars": (
                    len(detection_event.pattern) * detection_event.repetition_count
                ),
                "confidence": detection_event.confidence,
            },
        )

    async def configure(
        self,
        min_pattern_length: int = 100,
        max_pattern_length: int = 8000,
        min_repetitions: int = 2,
    ) -> None:
        self._min_pattern_length = min_pattern_length
        self._max_pattern_length = max_pattern_length
        self._min_repetitions = min_repetitions

        self._config = self._build_config()
        self._detector = self._create_internal_detector()

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
        return {
            "min_pattern_length": self._min_pattern_length,
            "max_pattern_length": self._max_pattern_length,
            "min_repetitions": self._min_repetitions,
            "detector": self._detector.get_stats(),
        }

    def _build_config(self) -> LoopDetectionConfig:
        chunk_size = max(1, self._min_pattern_length)
        config = LoopDetectionConfig(
            max_pattern_length=self._max_pattern_length,
            content_chunk_size=chunk_size,
            content_loop_threshold=max(2, self._min_repetitions),
        )
        errors = config.validate()
        if errors:
            raise ValueError(
                "Invalid loop detector configuration: " + ", ".join(errors)
            )
        return config

    def _create_internal_detector(self) -> InternalLoopDetector:
        detector = InternalLoopDetector(self._config)
        detector.enable()
        detector.reset()
        return detector
