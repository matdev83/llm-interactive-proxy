"""
Model Utilities

This module contains utility functions for working with model names and configurations.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from src.core.interfaces.model_bases import DomainModel


def parse_model_backend(model: str, default_backend: str = "") -> tuple[str, str]:
    """Parse model string to extract backend and actual model name.

    Handles multiple formats:
    - backend:model (e.g., "openrouter:gpt-4")
    - backend/model (e.g., "openrouter/gpt-4")
    - backend:model:version (e.g., "openrouter:anthropic/claude-3-haiku:beta")
    - backend/model:version (e.g., "openrouter/anthropic/claude-3-haiku:beta")
    - model (e.g., "gpt-4" - uses default backend)

    Args:
        model: Model string in various formats
        default_backend: Default backend to use if no prefix is specified

    Returns:
        Tuple of (backend_type, model_name)
    """
    # Find the first occurrence of either ':' or '/'
    colon_pos = model.find(":")
    slash_pos = model.find("/")

    # Determine which separator comes first (or if only one exists)
    separator_pos = -1
    if colon_pos != -1 and slash_pos != -1:
        # Both exist, use the first one
        separator_pos = min(colon_pos, slash_pos)
    elif colon_pos != -1:
        # Only colon exists
        separator_pos = colon_pos
    elif slash_pos != -1:
        # Only slash exists
        separator_pos = slash_pos

    if separator_pos != -1:
        # Split at the first separator
        backend = model[:separator_pos]
        model_name = model[separator_pos + 1 :]
        return backend, model_name
    else:
        # No separator found, use default backend
        return default_backend, model


# Model-specific reasoning configuration for config files
class ModelReasoningConfig(DomainModel):
    """Configuration for model-specific reasoning defaults."""

    # OpenAI/OpenRouter reasoning parameters
    reasoning_effort: str | None = Field(
        None, description="Default reasoning effort for this model (low/medium/high)"
    )
    reasoning: dict[str, Any] | None = Field(
        None, description="Default OpenRouter unified reasoning configuration"
    )

    # Gemini reasoning parameters
    thinking_budget: int | None = Field(
        None, description="Default Gemini thinking budget (128-32768 tokens)"
    )
    generation_config: dict[str, Any] | None = Field(
        None, description="Default Gemini generation configuration"
    )

    # Temperature configuration
    temperature: float | None = Field(
        None,
        description="Default temperature for this model (0.0-2.0 for OpenAI, 0.0-1.0 for Gemini)",
    )


class ModelDefaults(DomainModel):
    """Model-specific default configurations."""

    reasoning: ModelReasoningConfig | None = Field(
        None, description="Reasoning configuration defaults for this model"
    )

    # Loop detection default override for this model (backend/model or model)
    loop_detection_enabled: bool | None = Field(
        None, description="Enable/disable loop detection by default for this model"
    )

    # Tool call loop detection default overrides for this model
    # Spec-preferred names
    tool_loop_detection_enabled: bool | None = Field(
        None,
        description="Enable/disable tool call loop detection by default for this model",
    )
    tool_loop_detection_max_repeats: int | None = Field(
        None,
        description="Maximum number of consecutive identical tool calls before action is taken",
    )
    tool_loop_detection_ttl_seconds: int | None = Field(
        None,
        description="Time window in seconds for considering tool calls part of a pattern",
    )
    tool_loop_detection_mode: str | None = Field(
        None,
        description="How to handle detected tool call loops ('break' or 'chance_then_break')",
    )

    # Backward-compat aliases (read-only in apply_model_defaults)
    tool_loop_max_repeats: int | None = None
    tool_loop_ttl_seconds: int | None = None
    tool_loop_mode: str | None = None
