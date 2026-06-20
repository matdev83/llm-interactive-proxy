from __future__ import annotations

from src.core.domain.base import ValueObject


class LoopDetectionConfiguration(ValueObject):
    """Configuration for loop detection.

    This class handles standard remote LLM reply/content loop detection settings.
    """

    loop_detection_enabled: bool = False
    min_pattern_length: int = 100
    max_pattern_length: int = 8000

    def with_loop_detection_enabled(self, enabled: bool) -> LoopDetectionConfiguration:
        """Create a new config with updated loop detection enabled flag."""
        return self.model_copy(update={"loop_detection_enabled": enabled})

    def with_pattern_length_range(
        self, min_length: int, max_length: int
    ) -> LoopDetectionConfiguration:
        """Create a new config with updated pattern length range."""
        return self.model_copy(
            update={"min_pattern_length": min_length, "max_pattern_length": max_length}
        )
