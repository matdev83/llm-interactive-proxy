from __future__ import annotations

import logging
from typing import Any

from pydantic import field_validator

from src.core.domain.base import ValueObject

logger = logging.getLogger(__name__)


class ReasoningConfiguration(ValueObject):
    """Configuration for LLM reasoning parameters.

    This class handles reasoning settings like effort level, temperature,
    and model-specific generation parameters.
    """

    reasoning_effort: str | None = None
    thinking_budget: int | None = None
    temperature: float | None = None
    reasoning_config: dict[str, Any] | None = None
    gemini_generation_config: dict[str, Any] | None = None

    @classmethod
    @field_validator("thinking_budget")
    def validate_thinking_budget(cls, v: int | None) -> int | None:
        """Validate that the thinking budget is within acceptable range."""
        if v is not None and (v < 128 or v > 32768):
            raise ValueError("Thinking budget must be between 128 and 32768 tokens")
        return v

    @classmethod
    @field_validator("temperature")
    def validate_temperature(cls, v: float | None) -> float | None:
        """Validate that the temperature is within acceptable range."""
        if v is not None and (v < 0.0 or v > 2.0):
            raise ValueError(
                "Temperature must be between 0.0 and 2.0 "
                "(OpenAI supports up to 2.0, Gemini up to 1.0)"
            )
        return v

    def with_reasoning_effort(self, effort: str | None) -> ReasoningConfiguration:
        """Create a new config with updated reasoning effort."""
        return self.model_copy(update={"reasoning_effort": effort})

    def with_thinking_budget(self, budget: int | None) -> ReasoningConfiguration:
        """Create a new config with updated thinking budget."""
        return self.model_copy(update={"thinking_budget": budget})

    def with_temperature(self, temperature: float | None) -> ReasoningConfiguration:
        """Create a new config with updated temperature."""
        return self.model_copy(update={"temperature": temperature})

    def with_reasoning_config(
        self, config: dict[str, Any] | None
    ) -> ReasoningConfiguration:
        """Create a new config with updated reasoning configuration."""
        return self.model_copy(update={"reasoning_config": config})

    def with_gemini_generation_config(
        self, config: dict[str, Any] | None
    ) -> ReasoningConfiguration:
        """Create a new config with updated Gemini generation configuration."""
        return self.model_copy(update={"gemini_generation_config": config})
