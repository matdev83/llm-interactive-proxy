"""Utility functions for recalculating token usage after content transformations.

This module provides utilities for:
1. Calculating outbound tokens (what we send to backends after transformations)
2. Recalculating inbound tokens (what we receive after proxy transformations)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.domain.openrouter_usage import OpenRouterUsage

logger = logging.getLogger(__name__)


def _serialize_for_token_count(value: Any) -> str:
    """Serialize arbitrary request fields into stable token-countable text."""
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, bytes | bytearray):
        return value.decode("utf-8", errors="ignore")

    candidate = value
    if hasattr(candidate, "model_dump"):
        try:
            dumped = candidate.model_dump()  # type: ignore[attr-defined]
            if dumped is not None:
                candidate = dumped
        except Exception:
            pass

    try:
        return json.dumps(
            candidate,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except Exception:
        return str(candidate)


def _coerce_request_payload(request_data: Any) -> dict[str, Any] | None:
    """Coerce request_data into a plain dictionary when possible."""
    if isinstance(request_data, dict):
        return request_data

    if hasattr(request_data, "model_dump"):
        try:
            dumped = request_data.model_dump()  # type: ignore[attr-defined]
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass

    if hasattr(request_data, "dict"):
        try:
            dumped = request_data.dict()  # type: ignore[attr-defined]
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass

    payload: dict[str, Any] = {}
    for field_name in (
        "messages",
        "input",
        "tools",
        "functions",
        "tool_choice",
        "response_format",
    ):
        if hasattr(request_data, field_name):
            payload[field_name] = getattr(request_data, field_name)

    return payload or None


def _build_token_count_text(payload: dict[str, Any]) -> str:
    """Build a token-countable text representation of prompt-bearing fields."""
    from src.core.utils.token_count import extract_prompt_text

    text_parts: list[str] = []

    messages = payload.get("messages")
    if isinstance(messages, list):
        prompt_text = extract_prompt_text(messages)
        if prompt_text:
            text_parts.append(prompt_text)

    # Responses API style input payloads can carry prompt-bearing content even when
    # messages are absent.
    if not text_parts and payload.get("input") is not None:
        text_parts.append(_serialize_for_token_count(payload.get("input")))

    # Tool schema and selection metadata are part of the model prompt budget.
    for key in ("tools", "functions", "tool_choice", "response_format"):
        value = payload.get(key)
        if value is None:
            continue
        serialized = _serialize_for_token_count(value)
        if serialized:
            text_parts.append(f"{key}:{serialized}")

    return "\n".join(part for part in text_parts if part)


def recalculate_usage_after_transformation(
    original_usage: dict[str, int] | OpenRouterUsage | None,
    original_content: str,
    transformed_content: str,
) -> OpenRouterUsage | None:
    """Recalculate token usage after content transformation.

    When the proxy transforms response content (e.g., pytest compression, filtering),
    the original usage counts from the backend no longer match the actual content.
    This function recalculates the completion tokens based on the transformed content.

    Args:
        original_usage: Original usage dict or OpenRouterUsage from backend
        original_content: Original content before transformation
        transformed_content: Content after transformation

    Returns:
        Updated OpenRouterUsage with recalculated completion_tokens, or None if no usage provided
    """
    if not original_usage:
        return None

    # Parse original usage if it's a dict
    if isinstance(original_usage, dict):
        base_usage = OpenRouterUsage.from_dict(original_usage)
        if not base_usage:
            return None
    else:
        base_usage = original_usage

    # If content wasn't actually transformed, return original usage
    if original_content == transformed_content:
        return base_usage

    from src.core.utils.token_count import count_tokens

    # Calculate tokens in transformed content
    transformed_tokens = count_tokens(transformed_content)

    # Preserve prompt tokens (input wasn't transformed)
    prompt_tokens = base_usage.prompt_tokens

    # Use transformed content token count as completion tokens
    completion_tokens = transformed_tokens

    # Log the recalculation for transparency
    original_completion = base_usage.completion_tokens
    if original_completion != completion_tokens:
        reduction = original_completion - completion_tokens
        reduction_pct = (
            (reduction / original_completion * 100) if original_completion > 0 else 0
        )
        logger.info(
            "Usage recalculated after content transformation: "
            "completion_tokens: %s -> %s "
            "(%s tokens / %.1f%% reduction), "
            "total_tokens: %s -> %s",
            original_completion,
            completion_tokens,
            reduction,
            reduction_pct,
            base_usage.total_tokens,
            prompt_tokens + completion_tokens,
        )

    return base_usage.with_recalculated_tokens(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )


def should_recalculate_usage(content: Any) -> bool:
    """Determine if usage should be recalculated based on content type.

    Usage recalculation is only meaningful for text content that can be tokenized.

    Args:
        content: The response content

    Returns:
        True if usage should be recalculated, False otherwise
    """
    # Only recalculate for dict responses (OpenAI-style chat completions)
    if not isinstance(content, dict):
        return False

    # Check if this looks like a chat completion response
    if "choices" not in content:
        return False

    # Check if there's actual text content to measure
    choices = content.get("choices", [])
    if not choices or not isinstance(choices, list):
        return False

    first_choice = choices[0] if choices else {}
    if not isinstance(first_choice, dict):
        return False

    # Check for message content (non-streaming)
    message = first_choice.get("message", {})
    if isinstance(message, dict) and message.get("content"):
        return True

    # Check for delta content (streaming)
    delta = first_choice.get("delta", {})
    return isinstance(delta, dict) and bool(delta.get("content"))


def extract_content_text(content: dict[str, Any]) -> str:
    """Extract text content from a chat completion response.

    Args:
        content: Chat completion response dict

    Returns:
        Extracted text content, or empty string if not found
    """
    try:
        choices = content.get("choices", [])
        if not choices:
            return ""

        first_choice = choices[0] if isinstance(choices, list) else {}
        if not isinstance(first_choice, dict):
            return ""

        # Try message content (non-streaming)
        message = first_choice.get("message", {})
        if isinstance(message, dict):
            msg_content = message.get("content")
            if isinstance(msg_content, str):
                return msg_content

        # Try delta content (streaming)
        delta = first_choice.get("delta", {})
        if isinstance(delta, dict):
            delta_content = delta.get("content")
            if isinstance(delta_content, str):
                return delta_content

        return ""
    except (ValueError, TypeError, AttributeError, KeyError):
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Failed to extract content text", exc_info=True)
        return ""


def calculate_outbound_tokens(
    request_data: Any,
    model: str | None = None,
    label: str = "outbound",
) -> int:
    """Calculate tokens in outbound request AFTER all proxy transformations.

    This calculates the actual number of tokens being sent to the backend,
    accounting for any content rewrites, filtering, or transformations
    applied by the proxy.

    Args:
        request_data: The request data being sent to backend (after transformations)
        model: Optional model name for encoding selection
        label: Optional label for logging (e.g., "outbound", "verbatim")

    Returns:
        Number of tokens in the outbound request
    """
    from src.core.utils.token_count import count_tokens

    try:
        payload = _coerce_request_payload(request_data)
        if payload is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Unknown request format: %s", type(request_data))
            return 0

        token_text = _build_token_count_text(payload)
        if not token_text:
            return 0

        token_count = count_tokens(token_text, model=model)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Calculated %s tokens for %s: %s tokens", label, model, token_count
            )

        return token_count

    except (ValueError, TypeError, AttributeError, KeyError):
        logger.warning("Failed to calculate outbound tokens", exc_info=True)
        return 0


def calculate_request_usage(
    request_data: Any,
    model: str | None = None,
) -> OpenRouterUsage:
    """Calculate complete usage information for outbound request.

    Args:
        request_data: The request data being sent to backend
        model: Optional model name

    Returns:
        OpenRouterUsage with prompt_tokens (outbound tokens)
    """
    prompt_tokens = calculate_outbound_tokens(request_data, model)

    return OpenRouterUsage.from_basic_usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=0,  # Not yet known
    )
