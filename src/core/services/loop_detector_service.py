from __future__ import annotations

import logging
from typing import Any

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
        self._config: dict[str, Any] = {}

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
            except Exception:
                return default

        min_len = _as_int(self._min_pattern_length, 50)
        max_len = _as_int(self._max_pattern_length, 500)
        min_reps = _as_int(self._min_repetitions, 2)

        if not content or len(content) < min_len * 2:
            return LoopDetectionResult(has_loop=False)

        try:
            config = LoopDetectionConfig(
                max_pattern_length=max_len, content_loop_threshold=min_reps
            )

            _ = InternalLoopDetector(config)
            results = []

            if len(content) >= min_len * 2:
                for pattern_length in range(min_len, min(max_len, len(content) // 2) + 1):
                    pattern = content[:pattern_length]
                    if content.count(pattern) >= min_reps:
                        results.append(
                            type(
                                "obj",
                                (object,),
                                {
                                    "repetitions": content.count(pattern),
                                    "pattern": pattern,
                                },
                            )()
                        )
                        break

            if results and results[0].repetitions >= min_reps:
                result = results[0]
                logger.warning(
                    f"Loop detected: {result.repetitions} repetitions of pattern (length {len(result.pattern)})"
                )

                return LoopDetectionResult(
                    has_loop=True,
                    pattern=result.pattern,
                    repetitions=result.repetitions,
                    details={
                        "pattern_length": len(result.pattern) if result.pattern else 0,
                        "total_repeated_chars": (
                            len(result.pattern) * result.repetitions if result.pattern else 0
                        ),
                    },
                )

            return LoopDetectionResult(has_loop=False)

        except Exception as e:
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

    async def register_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> None:
        return None

    async def clear_history(self) -> None:
        return None


