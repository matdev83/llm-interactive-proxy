"""Planning phase configuration for routing initial requests to a strong model."""

from __future__ import annotations

from typing import Any

from pydantic import ConfigDict, Field

from src.core.domain.base import ValueObject


class PlanningPhaseOverrides(ValueObject):
    """Optional parameter overrides applied during planning phase."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    temperature: float | None = Field(default=None, alias="temperature")
    top_p: float | None = Field(default=None, alias="top_p")
    reasoning_effort: str | None = Field(default=None, alias="reasoning_effort")
    thinking_budget: int | None = Field(default=None, alias="thinking_budget")
    reasoning: dict[str, Any] | None = Field(default=None, alias="reasoning")
    generation_config: dict[str, Any] | None = Field(
        default=None, alias="generation_config"
    )


from src.core.interfaces.configuration_interface import IPlanningPhaseConfig


class PlanningPhaseConfiguration(ValueObject, IPlanningPhaseConfig):
    """Configuration for planning phase model routing.

    This configuration allows routing the first N requests of a session to a stronger
    model for better planning and initial analysis, then switching back to a faster model.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    # Backing fields with default values
    enabled_value: bool = Field(default=False, alias="enabled")
    strong_model_value: str | None = Field(default=None, alias="strong_model")
    max_turns_value: int = Field(default=10, alias="max_turns")
    max_file_writes_value: int = Field(default=1, alias="max_file_writes")

    # Optional overrides for strong model parameters
    overrides: PlanningPhaseOverrides | None = Field(default=None, alias="overrides")

    # Interface-compliant properties
    @property
    def enabled(self) -> bool:
        return bool(self.enabled_value)

    @property
    def strong_model(self) -> str | None:
        return self.strong_model_value

    @property
    def max_turns(self) -> int:
        return int(self.max_turns_value)

    @property
    def max_file_writes(self) -> int:
        return int(self.max_file_writes_value)

    def with_enabled(self, enabled: bool) -> PlanningPhaseConfiguration:
        """Create a new configuration with updated enabled flag."""
        return self.model_copy(update={"enabled_value": enabled})

    def with_strong_model(self, strong_model: str | None) -> PlanningPhaseConfiguration:
        """Create a new configuration with updated strong model."""
        return self.model_copy(update={"strong_model_value": strong_model})

    def with_max_turns(self, max_turns: int) -> PlanningPhaseConfiguration:
        """Create a new configuration with updated max turns."""
        return self.model_copy(update={"max_turns_value": max_turns})

    def with_max_file_writes(self, max_file_writes: int) -> PlanningPhaseConfiguration:
        """Create a new configuration with updated max file writes."""
        return self.model_copy(update={"max_file_writes_value": max_file_writes})
