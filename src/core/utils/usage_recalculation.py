"""Utility functions for recalculating token usage after content transformations.

This module provides utilities for:
1. Calculating outbound tokens (what we send to backends after transformations)
2. Recalculating inbound tokens (what we receive after proxy transformations)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def recalculate_usage_after_transformation(
    original_usage: dict[str, int] | None,
    original_content: str,
    transformed_content: str,
) -> dict[str, int] | None:
    """Recalculate token usage after content transformation.

    When the proxy transforms response content (e.g., pytest compression, filtering),
    the original usage counts from the backend no longer match the actual content.
    This function recalculates the completion tokens based on the transformed content.

    Args:
        original_usage: Original usage dict from backend with prompt_tokens, completion_tokens, total_tokens
        original_content: Original content before transformation
        transformed_content: Content after transformation

    Returns:
        Updated usage dict with recalculated completion_tokens, or None if no usage provided
    """
    if not original_usage:
        return None

    # If content wasn't actually transformed, return original usage
    if original_content == transformed_content:
        return original_usage

    from src.core.utils.token_count import count_tokens

    # Calculate tokens in transformed content
    transformed_tokens = count_tokens(transformed_content)

    # Preserve prompt tokens (input wasn't transformed)
    prompt_tokens = original_usage.get("prompt_tokens", 0)

    # Use transformed content token count as completion tokens
    completion_tokens = transformed_tokens

    # Calculate new total
    total_tokens = prompt_tokens + completion_tokens

    # Log the recalculation for transparency
    original_completion = original_usage.get("completion_tokens", 0)
    if original_completion != completion_tokens:
        reduction = original_completion - completion_tokens
        reduction_pct = (
            (reduction / original_completion * 100) if original_completion > 0 else 0
        )
        logger.info(
            f"Usage recalculated after content transformation: "
            f"completion_tokens: {original_completion} -> {completion_tokens} "
            f"({reduction} tokens / {reduction_pct:.1f}% reduction), "
            f"total_tokens: {original_usage.get('total_tokens', 0)} -> {total_tokens}"
        )

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


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
        logger.debug("Failed to extract content text", exc_info=True)
        return ""


def calculate_outbound_tokens(
    request_data: Any,
    model: str | None = None,
) -> int:
    """Calculate tokens in outbound request AFTER all proxy transformations.

    This calculates the actual number of tokens being sent to the backend,
    accounting for any content rewrites, filtering, or transformations
    applied by the proxy.

    Args:
        request_data: The request data being sent to backend (after transformations)
        model: Optional model name for encoding selection

    Returns:
        Number of tokens in the outbound request
    """
    from src.core.utils.token_count import count_tokens, extract_prompt_text

    try:
        # Handle different request formats
        if hasattr(request_data, "messages"):
            # Pydantic model or object with messages attribute
            messages = request_data.messages
        elif isinstance(request_data, dict):
            # Dict format
            messages = request_data.get("messages", [])
        else:
            logger.debug(f"Unknown request format: {type(request_data)}")
            return 0

        # Extract and count tokens from messages
        prompt_text = extract_prompt_text(messages)
        token_count = count_tokens(prompt_text, model=model)

        logger.debug(f"Calculated outbound tokens for {model}: {token_count} tokens")

        return token_count

    except (ValueError, TypeError, AttributeError, KeyError):
        logger.warning("Failed to calculate outbound tokens", exc_info=True)
        return 0


def calculate_request_usage(
    request_data: Any,
    model: str | None = None,
) -> dict[str, int]:
    """Calculate complete usage information for outbound request.

    Args:
        request_data: The request data being sent to backend
        model: Optional model name

    Returns:
        Dictionary with prompt_tokens (outbound tokens)
    """
    prompt_tokens = calculate_outbound_tokens(request_data, model)

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": 0,  # Not yet known
        "total_tokens": prompt_tokens,
    }
