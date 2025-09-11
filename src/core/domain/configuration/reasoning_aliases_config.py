from __future__ import annotations

from pydantic import BaseModel, Field


class ReasoningMode(BaseModel):
    """
    Defines the settings for a specific reasoning mode.
    """

    max_reasoning_tokens: int | None = None
    reasoning_effort: str | None = None
    user_prompt_prefix: str | None = None
    user_prompt_suffix: str | None = None
    temperature: float | None = None
    top_p: float | None = None


class ModelReasoningAliases(BaseModel):
    """
    Contains the reasoning modes for a specific model.
    """

    model: str
    modes: dict[str, ReasoningMode] = Field(default_factory=dict)


class ReasoningAliasesConfig(BaseModel):
    """
    The root model for the reasoning_aliases.yaml configuration file.
    """

    reasoning_alias_settings: list[ModelReasoningAliases]
