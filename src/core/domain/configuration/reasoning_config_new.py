from __future__ import annotations

import logging
from typing import Any

from pydantic import field_validator

from src.core.domain.base import ValueObject
from src.core.interfaces.configuration import IReasoningConfig

logger = logging.getLogger(__name__)


class ReasoningConfigurationNew(ValueObject, IReasoningConfig):
    """Configuration for LLM reasoning parameters.

    This class handles reasoning settings like effort level, temperature,
    and model-specific generation parameters.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Initialize attributes if not already set
        if not hasattr(self, "reasoning_effort"):
            self.reasoning_effort = None
        if not hasattr(self, "thinking_budget"):
            self.thinking_budget = None
        if not hasattr(self, "temperature"):
            self.temperature = None
        if not hasattr(self, "reasoning_config"):
            self.reasoning_config = None
        if not hasattr(self, "gemini_generation_config"):
            self.gemini_generation_config = None

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

    def with_reasoning_effort(self, effort: str | None) -> ReasoningConfigurationNew:
        """Create a new config with updated reasoning effort."""
        return self.model_copy(update={"reasoning_effort": effort})

    def with_thinking_budget(self, budget: int | None) -> ReasoningConfigurationNew:
        """Create a new config with updated thinking budget."""
        return self.model_copy(update={"thinking_budget": budget})

    def with_temperature(self, temperature: float | None) -> ReasoningConfigurationNew:
        """Create a new config with updated temperature."""
        return self.model_copy(update={"temperature": temperature})

    def with_reasoning_config(
        self, config: dict[str, Any] | None
    ) -> ReasoningConfigurationNew:
        """Create a new config with updated reasoning configuration."""
        return self.model_copy(update={"reasoning_config": config})

    def with_gemini_generation_config(
        self, config: dict[str, Any] | None
    ) -> ReasoningConfigurationNew:
        """Create a new config with updated Gemini generation configuration."""
        return self.model_copy(update={"gemini_generation_config": config})
