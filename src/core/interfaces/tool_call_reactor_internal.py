"""
Internal typed contracts for the tool-call reactor subsystem.

This module defines typed data models used internally by the tool-call reactor
subsystem to normalize tool arguments and maintain type safety across component
boundaries. External/public integration points remain compatible (notably
ToolCallContext.tool_arguments remains a legacy dictionary), but the subsystem
produces that dictionary only at the boundary from these typed internal contracts.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from json_repair import repair_json
from pydantic import BaseModel, Field, RootModel

logger = logging.getLogger(__name__)


class NormalizedToolArguments(RootModel[dict[str, Any]]):
    """JSON-object-like arguments normalized for reactor handler invocation.

    This RootModel wraps a dict[str, Any] to ensure all tool arguments are
    represented as dictionary objects internally, even when the original input
    was an array or raw text. Non-object inputs are wrapped using reserved keys.
    """


class ToolArgumentsEnvelope(BaseModel):
    """Typed envelope for tool arguments passed through the reactor subsystem.

    This model is the single internal representation for tool arguments across
    streaming/non-streaming paths. It tracks parsing outcomes, preserves raw
    input when needed, and normalizes all argument shapes into a consistent
    dictionary format.

    Normalization rules:
    - If parsed arguments are a JSON object → normalized_arguments.root is that object
    - If parsed arguments are a JSON array → normalized_arguments.root = {"__proxy_args_list__": <array>}
    - If parsing fails and only raw text exists → normalized_arguments.root = {"__proxy_args_raw__": <raw_text>}
    """

    parse_outcome: Literal["success", "recovered", "failed"] = "failed"
    """Indicates whether argument parsing succeeded, was recovered via repair, or failed."""

    raw_arguments: str | None = None
    """Original raw argument string before parsing, if available."""

    normalized_arguments: NormalizedToolArguments = Field(
        default_factory=lambda: NormalizedToolArguments({})
    )
    """Normalized dictionary representation of tool arguments."""

    was_modified_by_fixups: bool = False
    """Indicates whether argument fixups (path normalization, Windows separators, etc.) were applied."""


def normalize_tool_arguments(
    raw_input: Any,
    parse_outcome: Literal["success", "recovered", "failed"] | None = None,
    was_modified_by_fixups: bool = False,
) -> ToolArgumentsEnvelope:
    """Normalize tool arguments into a typed envelope.

    This function converts various input shapes (dict, list, str) into a
    consistent ToolArgumentsEnvelope following the normalization rules:
    - JSON object → normalized_arguments.root is that object
    - JSON array → normalized_arguments.root = {"__proxy_args_list__": <array>}
    - Raw/unparsed text → normalized_arguments.root = {"__proxy_args_raw__": <raw_text>}

    Args:
        raw_input: The raw tool arguments input. Can be:
            - A dictionary (already parsed JSON object)
            - A list (already parsed JSON array)
            - A string (may be JSON string or raw text)
        parse_outcome: Optional parse outcome. If None, will be inferred:
            - "success" if input is dict/list (already parsed)
            - "failed" if input is str and cannot be parsed
            - "recovered" if input is str and was repaired
        was_modified_by_fixups: Whether fixups were applied to the arguments.

    Returns:
        ToolArgumentsEnvelope with normalized arguments and metadata.
    """
    # Reserved keys for internal normalization
    PROXY_ARGS_LIST_KEY = "__proxy_args_list__"
    PROXY_ARGS_RAW_KEY = "__proxy_args_raw__"

    # Handle already-parsed dictionary (most common case)
    if isinstance(raw_input, dict):
        outcome = parse_outcome if parse_outcome is not None else "success"
        return ToolArgumentsEnvelope(
            parse_outcome=outcome,
            normalized_arguments=NormalizedToolArguments(raw_input),
            was_modified_by_fixups=was_modified_by_fixups,
        )

    # Handle already-parsed list
    if isinstance(raw_input, list):
        outcome = parse_outcome if parse_outcome is not None else "success"
        wrapped = {PROXY_ARGS_LIST_KEY: raw_input}
        return ToolArgumentsEnvelope(
            parse_outcome=outcome,
            normalized_arguments=NormalizedToolArguments(wrapped),
            was_modified_by_fixups=was_modified_by_fixups,
        )

    # Handle string input (may be JSON or raw text)
    if isinstance(raw_input, str):
        raw_text = raw_input
        outcome = parse_outcome if parse_outcome is not None else "failed"

        # Try to parse as JSON
        parsed_value: Any | None = None
        if parse_outcome is None:
            # Attempt parsing if outcome not provided
            try:
                parsed_value = json.loads(raw_text)
                outcome = "success"
            except (json.JSONDecodeError, TypeError, ValueError):
                # Try repair
                try:
                    repaired = repair_json(raw_text)
                    if isinstance(repaired, str):
                        try:
                            parsed_value = json.loads(repaired)
                            outcome = "recovered"
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
                except Exception as exc:
                    # Log repair failures for debugging
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "JSON repair failed during tool arguments normalization",
                            exc_info=True,
                        )

        # If we have a parsed value, normalize it
        if parsed_value is not None:
            if isinstance(parsed_value, dict):
                return ToolArgumentsEnvelope(
                    parse_outcome=outcome,
                    raw_arguments=raw_text,
                    normalized_arguments=NormalizedToolArguments(parsed_value),
                    was_modified_by_fixups=was_modified_by_fixups,
                )
            elif isinstance(parsed_value, list):
                wrapped = {PROXY_ARGS_LIST_KEY: parsed_value}
                return ToolArgumentsEnvelope(
                    parse_outcome=outcome,
                    raw_arguments=raw_text,
                    normalized_arguments=NormalizedToolArguments(wrapped),
                    was_modified_by_fixups=was_modified_by_fixups,
                )
            else:
                # Other parsed types (str, int, bool, etc.) - wrap as raw
                wrapped_raw: dict[str, Any] = {PROXY_ARGS_RAW_KEY: raw_text}
                return ToolArgumentsEnvelope(
                    parse_outcome=outcome,
                    raw_arguments=raw_text,
                    normalized_arguments=NormalizedToolArguments(wrapped_raw),
                    was_modified_by_fixups=was_modified_by_fixups,
                )

        # Failed to parse - wrap raw text
        wrapped_failed: dict[str, Any] = {PROXY_ARGS_RAW_KEY: raw_text}
        return ToolArgumentsEnvelope(
            parse_outcome=outcome,
            raw_arguments=raw_text,
            normalized_arguments=NormalizedToolArguments(wrapped_failed),
            was_modified_by_fixups=was_modified_by_fixups,
        )

    # Fallback for other types (int, bool, None, etc.) - wrap as raw
    wrapped_fallback: dict[str, Any] = {PROXY_ARGS_RAW_KEY: str(raw_input)}
    outcome_fallback = parse_outcome if parse_outcome is not None else "failed"
    return ToolArgumentsEnvelope(
        parse_outcome=outcome_fallback,
        raw_arguments=str(raw_input),
        normalized_arguments=NormalizedToolArguments(wrapped_fallback),
        was_modified_by_fixups=was_modified_by_fixups,
    )
