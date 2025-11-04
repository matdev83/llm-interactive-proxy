"""
Model Utilities

This module contains utility functions for working with model names and configurations.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs

from pydantic import Field

logger = logging.getLogger(__name__)

from src.core.domain.model_capabilities import ModelLimits
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
    colon_pos: int = model.find(":")
    slash_pos: int = model.find("/")

    # Determine which separator comes first (or if only one exists)
    separator_pos: int = -1
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
        backend: str = model[:separator_pos]
        model_name: str = model[separator_pos + 1 :]
        return backend, model_name
    else:
        # No separator found, use default backend
        return default_backend, model


def parse_model_with_params(
    model: str, default_backend: str = ""
) -> tuple[str, str, dict[str, Any]]:
    """Parse model string with optional URI parameters.

    Handles multiple formats with optional query parameters:
    - backend:model?params (e.g., "openai:gpt-4?temperature=0.5")
    - backend:model_group/model?params (e.g., "openai:anthropic/claude?temperature=0.2")
    - backend/model?params (e.g., "openai/gpt-4?temperature=0.5")
    - model?params (e.g., "gpt-4?temperature=0.5" - uses default backend)

    Query parameters are parsed from the portion after '?' using standard URL query syntax.
    Multiple parameters can be specified: ?temperature=0.5&reasoning_effort=high

    Args:
        model: Model string with optional query parameters
        default_backend: Default backend to use if no prefix is specified

    Returns:
        Tuple of (backend_type, model_name, uri_params)
        where uri_params is a dict with parsed parameter values

    Examples:
        >>> parse_model_with_params("openai:gpt-4?temperature=0.5")
        ("openai", "gpt-4", {"temperature": ["0.5"]})

        >>> parse_model_with_params("backend:model_group/model?temperature=0.2&reasoning_effort=low")
        ("backend", "model_group/model", {"temperature": ["0.2"], "reasoning_effort": ["low"]})

        >>> parse_model_with_params("openai:gpt-4")
        ("openai", "gpt-4", {})
    """
    uri_params: dict[str, Any] = {}

    try:
        base_model = model
        query_string = ""

        # Special handling for hybrid model syntax, e.g., hybrid:[...model?params]
        if model.startswith("hybrid:[") and model.endswith("]") and "?" in model:
            question_mark_pos = model.rfind("?")
            # Ensure '?' is inside the brackets before splitting
            if question_mark_pos > model.find("["):
                base_model = model[:question_mark_pos] + "]"
                query_string = model[question_mark_pos + 1 : -1]  # Exclude '?' and ']'
        # Standard syntax: backend:model?params
        elif "?" in model:
            parts = model.split("?", 1)
            base_model = parts[0]
            if len(parts) > 1:
                query_string = parts[1]

        # Parse query string if it exists
        if query_string:
            try:
                parsed_params = parse_qs(query_string, keep_blank_values=False)

                # Convert single-value lists to scalar values for convenience
                # e.g., {"temperature": ["0.5"]} -> {"temperature": "0.5"}
                for key, value_list in parsed_params.items():
                    if len(value_list) == 1:
                        uri_params[key] = value_list[0]
                    else:
                        # Multiple values for same parameter - use the last one
                        uri_params[key] = value_list[-1]
                        logger.debug(
                            f"Multiple values for parameter '{key}': {value_list}, using last value: {value_list[-1]}"
                        )

                logger.debug(
                    f"Parsed URI parameters from model string '{model}': {uri_params}"
                )
            except Exception as parse_error:
                # Log warning for malformed query string but continue
                logger.warning(
                    f"Malformed URI query string in model '{model}': {parse_error}. "
                    f"Continuing without URI parameters."
                )
                uri_params = {}

        # Parse the base model string (without query parameters) using existing function
        backend_type, model_name = parse_model_backend(base_model, default_backend)

        return backend_type, model_name, uri_params

    except Exception as e:
        # Graceful error handling - log warning and fall back to no parameters
        logger.warning(
            f"Failed to parse URI parameters from model string '{model}': {e}. "
            f"Continuing without URI parameters."
        )
        # Fall back to existing parse_model_backend
        try:
            backend_type, model_name = parse_model_backend(model, default_backend)
        except Exception as fallback_error:
            # If even the fallback fails, log error and use defaults
            logger.error(
                f"Failed to parse model string '{model}' even without URI parameters: {fallback_error}. "
                f"Using default backend '{default_backend}' and model '{model}'."
            )
            backend_type = default_backend if default_backend else "openai"
            model_name = model
        return backend_type, model_name, {}


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

    # Per-model token/context limits that can be enforced at the front-end
    limits: ModelLimits | None = Field(
        None,
        description=(
            "Limits and constraints for this model, such as max_input_tokens "
            "(applied at the front-end)."
        ),
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
