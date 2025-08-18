"""
Loop Detector Service

Implements loop detection for repetitive content in responses.
"""

from __future__ import annotations

import logging
from typing import Any

from src.core.interfaces.loop_detector_interface import ILoopDetector, LoopDetectionResult
from src.loop_detection.config import LoopDetectionConfig
from src.loop_detection.detector import LoopDetector as InternalLoopDetector

logger = logging.getLogger(__name__)


class LoopDetector(ILoopDetector):
    """Implements loop detection for repetitive content."""

    def __init__(
        self,
        min_pattern_length: int = 50,
        max_pattern_length: int = 500,
        min_repetitions: int = 2,
        max_samples: int = 20,
    ):
        """Initialize the loop detector.

        Args:
            min_pattern_length: Minimum pattern length to consider
            max_pattern_length: Maximum pattern length to analyze
            min_repetitions: Minimum repetitions required to declare a loop
            max_samples: Maximum samples to analyze from content
        """
        self._min_pattern_length = min_pattern_length
        self._max_pattern_length = max_pattern_length
        self._min_repetitions = min_repetitions
        self._max_samples = max_samples
        self._config: dict[str, Any] = {}

    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        """Check for repetitive patterns in content.

        Args:
            content: The content to check

        Returns:
            LoopDetectionResult with loop detection information
        """

        # Coerce configuration values to integers if misconfigured
        def _as_int(value: Any, default: int) -> int:
            try:
                if isinstance(value, int):
                    return value
                if isinstance(value, dict):
                    # Try common keys
                    for k in (
                        "min_pattern_length",
                        "max_pattern_length",
                        "min_repetitions",
                        "value",
                    ):
                        if k in value and isinstance(value[k], int):
                            return int(value[k])
                # Try attribute access
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
                return int(value)  # last resort
            except Exception:
                return default

        min_len = _as_int(self._min_pattern_length, 50)
        max_len = _as_int(self._max_pattern_length, 500)
        min_reps = _as_int(self._min_repetitions, 2)

        if not content or len(content) < min_len * 2:
            # Not enough content to check for loops
            return LoopDetectionResult(has_loop=False)

        try:
            # Configure detection parameters
            config = LoopDetectionConfig(
                max_pattern_length=max_len, content_loop_threshold=min_reps
            )

            # Call the loop detection algorithm
            _ = InternalLoopDetector(config)
            # Process the content in chunks to check for loops
            # This is a simplified approach - a full implementation would be more sophisticated
            results = []  # Placeholder for actual implementation

            # For now, let's implement a basic pattern detection
            # This is a simplified version and should be replaced with the actual detector logic
            if len(content) >= min_len * 2:
                # Simple repetitive pattern detection
                for pattern_length in range(
                    min_len, min(max_len, len(content) // 2) + 1
                ):
                    # Check if pattern repeats
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
                # Loop detected
                result = results[0]
                logger.warning(
                    f"Loop detected: {result.repetitions} repetitions "
                    f"of pattern (length {len(result.pattern)})"
                )

                return LoopDetectionResult(
                    has_loop=True,
                    pattern=result.pattern,
                    repetitions=result.repetitions,
                    details={
                        "pattern_length": len(result.pattern) if result.pattern else 0,
                        "total_repeated_chars": (
                            len(result.pattern) * result.repetitions
                            if result.pattern
                            else 0
                        ),
                    },
                )

            # No loop detected
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
        """Update configuration parameters.

        Args:
            min_pattern_length: Minimum length of pattern to detect
            max_pattern_length: Maximum length of pattern to detect
            min_repetitions: Minimum number of repetitions to consider a loop
        """
        self._min_pattern_length = min_pattern_length
        self._max_pattern_length = max_pattern_length
        self._min_repetitions = min_repetitions

        logger.debug(
            f"Loop detector configuration updated: min_pattern_length={min_pattern_length}, max_pattern_length={max_pattern_length}, min_repetitions={min_repetitions}"
        )

    async def register_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> None:
        """Register a tool call for future loop detection.

        Args:
            tool_name: The name of the tool being called
            arguments: The arguments passed to the tool
        """
        # Implementation would go here

    async def clear_history(self) -> None:
        """Clear all recorded history."""
        # Implementation would go here


def create_loop_detector(
    min_pattern_length: int = 50,
    max_pattern_length: int = 500,
    min_repetitions: int = 2,
    max_samples: int = 20,
) -> LoopDetector:
    """Create a loop detector with the specified configuration.

    Args:
        min_pattern_length: Minimum pattern length to consider
        max_pattern_length: Maximum pattern length to analyze
        min_repetitions: Minimum repetitions required to declare a loop
        max_samples: Maximum samples to analyze from content

    Returns:
        A configured loop detector instance
    """
    return LoopDetector(
        min_pattern_length=min_pattern_length,
        max_pattern_length=max_pattern_length,
        min_repetitions=min_repetitions,
        max_samples=max_samples,
    )
