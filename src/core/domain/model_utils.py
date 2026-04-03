"""
Model Utilities

This module contains utility functions for working with model names and configurations.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import parse_qs

from pydantic import BaseModel, Field
from pydantic.types import JsonValue

logger = logging.getLogger(__name__)

from src.core.domain.model_capabilities import ModelLimits
from src.core.interfaces.model_bases import DomainModel


class ParsedModelWithParams(BaseModel):
    """Result of parsing a model string with URI parameters.

    Contains the parsed backend type, model name, and any URI parameters.
    """

    backend_type: str = Field(
        description="The backend type (e.g., 'openai', 'anthropic')"
    )
    model_name: str = Field(description="The model name (e.g., 'gpt-4', 'claude-3')")
    uri_params: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="URI parameters parsed from query string (e.g., {'temperature': '0.5'})",
    )


class ParsedModel(BaseModel):
    """Result of parsing a model string into backend and model name."""

    backend_type: str = Field(
        description="The backend type (e.g., 'openai', 'anthropic')"
    )
    model_name: str = Field(description="The model name (e.g., 'gpt-4', 'claude-3')")


def has_explicit_backend_selector(model: str) -> bool:
    """Return whether the selector uses explicit `backend:model` routing syntax.

    Backend selection is explicit only when the first `:` appears before the first
    `/` in the route portion (before any query string).
    """

    route_portion, _, _ = model.partition("?")
    first_colon_index = route_portion.find(":")
    if first_colon_index < 0:
        return False
    first_slash_index = route_portion.find("/")
    return first_slash_index < 0 or first_colon_index < first_slash_index


def parse_model_backend(model: str, default_backend: str = "") -> ParsedModel:
    """Parse model string to extract backend and actual model name.

    Supported formats:
    - backend:model (e.g., "openrouter:gpt-4")
    - backend:model_path (e.g., "openrouter:anthropic/claude-3-haiku:beta")
    - model (e.g., "gpt-4" - uses default_backend)
    - vendor/model (e.g., "openai/gpt-4o" - treated as a model identifier, not backend selection)

    Args:
        model: Model string in various formats
        default_backend: Default backend to use if no prefix is specified

    Returns:
        ParsedModel with backend_type and model_name fields
    """
    # IMPORTANT: Backend selection uses ONLY ":" and only when it appears before
    # the first "/" in the route portion. This keeps selectors like
    # "vendor/model:free" in model-only mode.
    if has_explicit_backend_selector(model):
        backend, model_name = model.split(":", 1)
        return ParsedModel(backend_type=backend, model_name=model_name)

    return ParsedModel(backend_type=default_backend, model_name=model)


def parse_model_with_params(
    model: str, default_backend: str = ""
) -> ParsedModelWithParams:
    """Parse model string with optional URI parameters.

    Handles multiple formats with optional query parameters:
    - backend:model?params (e.g., "openai:gpt-4?temperature=0.5")
    - backend:model_group/model?params (e.g., "openai:anthropic/claude?temperature=0.2")
    - model?params (e.g., "gpt-4?temperature=0.5" - uses default backend)
    - vendor/model?params (e.g., "openai/gpt-4o?temperature=0.5" - treated as a model identifier)

    Query parameters are parsed from portion after '?' using standard URL query syntax.
    Multiple parameters can be specified: ?temperature=0.5&reasoning_effort=high

    Args:
        model: Model string with optional query parameters
        default_backend: Default backend to use if no prefix is specified

    Returns:
        ParsedModelWithParams with backend_type, model_name, and uri_params fields

    Examples:
        >>> result = parse_model_with_params("openai:gpt-4?temperature=0.5")
        result.backend_type == "openai"
        result.model_name == "gpt-4"
        result.uri_params == {"temperature": "0.5"}

        >>> result = parse_model_with_params("backend:model_group/model?temperature=0.2&reasoning_effort=low")
        result.backend_type == "backend"
        result.model_name == "model_group/model"
        result.uri_params == {"temperature": "0.2", "reasoning_effort": "low"}

        >>> result = parse_model_with_params("openai:gpt-4")
        result.backend_type == "openai"
        result.model_name == "gpt-4"
        result.uri_params == {}
    """
    uri_params: dict[str, JsonValue] = {}

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
                        # Multiple values for same parameter - use last one
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
                    f"Continuing without URI parameters.",
                    exc_info=True,
                )
                uri_params = {}

        # Parse base model string (without query parameters) using existing function
        parsed_model = parse_model_backend(base_model, default_backend)

        return ParsedModelWithParams(
            backend_type=parsed_model.backend_type,
            model_name=parsed_model.model_name,
            uri_params=uri_params,
        )

    except Exception as e:
        # Graceful error handling - log warning and fall back to no parameters
        logger.warning(
            f"Failed to parse URI parameters from model string '{model}': {e}. "
            f"Continuing without URI parameters.",
            exc_info=True,
        )
        # Fall back to existing parse_model_backend
        try:
            parsed_model = parse_model_backend(model, default_backend)
            backend_type = parsed_model.backend_type
            model_name = parsed_model.model_name
        except Exception as fallback_error:
            # If even the fallback fails, log error and use defaults
            logger.error(
                f"Failed to parse model string '{model}' even without URI parameters: {fallback_error}. "
                f"Using default backend '{default_backend}' and model '{model}'.",
                exc_info=True,
            )
            backend_type = default_backend if default_backend else "openai"
            model_name = model
        return ParsedModelWithParams(
            backend_type=backend_type, model_name=model_name, uri_params={}
        )


# Model-specific reasoning configuration for config files
class ModelReasoningConfig(DomainModel):
    """Configuration for model-specific reasoning defaults."""

    # OpenAI/OpenRouter reasoning parameters
    reasoning_effort: str | None = Field(
        None,
        description="Default reasoning effort for this model (low/medium/high/xhigh)",
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

    # Loop detection default override for this model (backend:model or model)
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
