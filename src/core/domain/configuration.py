from __future__ import annotations

from src.core.domain.base import ValueObject
from src.core.interfaces.configuration_interface import (
    ILoopDetectionConfig,
    IReasoningConfig,
)


class ReasoningConfig(ValueObject, IReasoningConfig):
    """Configuration for reasoning parameters."""

    reasoning_effort: str | None = None
    thinking_budget: int | None = None
    temperature: float | None = None

    def with_reasoning_effort(self, effort: str | None) -> IReasoningConfig:
        """Create a new config with updated reasoning effort."""
        return self.model_copy(update={"reasoning_effort": effort})

    def with_thinking_budget(self, budget: int | None) -> IReasoningConfig:
        """Create a new config with updated thinking budget."""
        return self.model_copy(update={"thinking_budget": budget})

    def with_temperature(self, temperature: float | None) -> IReasoningConfig:
        """Create a new config with updated temperature."""
        return self.model_copy(update={"temperature": temperature})


class LoopDetectionConfig(ValueObject, ILoopDetectionConfig):
    """Configuration for loop detection."""

    loop_detection_enabled: bool = True
    tool_loop_detection_enabled: bool = True
    min_pattern_length: int = 100  # Based on memory ID 3368303
    max_pattern_length: int = 8000  # Based on memory ID 3368303

    def with_loop_detection_enabled(self, enabled: bool) -> ILoopDetectionConfig:
        """Create a new config with updated loop detection enabled flag."""
        return self.model_copy(update={"loop_detection_enabled": enabled})

    def with_tool_loop_detection_enabled(self, enabled: bool) -> ILoopDetectionConfig:
        """Create a new config with updated tool loop detection enabled flag."""
        return self.model_copy(update={"tool_loop_detection_enabled": enabled})

    def with_pattern_length_range(
        self, min_length: int, max_length: int
    ) -> ILoopDetectionConfig:
        """Create a new config with updated pattern length range."""
        return self.model_copy(
            update={"min_pattern_length": min_length, "max_pattern_length": max_length}
        )
