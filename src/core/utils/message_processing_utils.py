from __future__ import annotations

import logging
from typing import Any

from src.core.services import metrics_service

logger = logging.getLogger(__name__)

# Marker key used to track if a message has been processed
_PROCESSING_MARKER = "_tool_calls_processed"


def is_message_processed(message: Any) -> bool:
    """Check if a message has already been processed for tool calls.

    This function checks for a processing marker that indicates whether
    the message's tool calls have already been extracted, repaired, or
    otherwise processed. This prevents redundant processing of historical
    messages in conversation history.

    Args:
        message: The message to check. Can be a dict or an object with attributes.

    Returns:
        True if the message has been processed, False otherwise.

    Examples:
        >>> msg = {"role": "assistant", "content": "Hello"}
        >>> is_message_processed(msg)
        False
        >>> mark_message_processed(msg)
        >>> is_message_processed(msg)
        True
    """
    is_processed = False
    if isinstance(message, dict):
        is_processed = bool(message.get(_PROCESSING_MARKER, False))
    else:
        is_processed = bool(getattr(message, _PROCESSING_MARKER, False))

    return is_processed


def mark_message_processed(message: Any) -> None:
    """Mark a message as processed for tool calls.

    This function adds a processing marker to the message to indicate that
    its tool calls have been extracted, repaired, or otherwise processed.
    This marker is used to skip redundant processing of historical messages.

    The is added as metadata and does not modify the core message
    structure (role, content, tool_calls, etc.).

    Args:
        message: The message to mark. Can be a dict or an object with attributes.

    Examples:
        >>> msg = {"role": "assistant", "content": "Hello"}
        >>> mark_message_processed(msg)
        >>> msg["_tool_calls_processed"]
        True
    """
    # Check if message was already processed before marking
    was_already_processed = is_message_processed(message)

    if isinstance(message, dict):
        message[_PROCESSING_MARKER] = True
    else:
        setattr(message, _PROCESSING_MARKER, True)

    # Only increment counter if this is the first time processing this message
    if not was_already_processed:
        metrics_service.inc("tool_call.messages.processed")


def increment_processed_counter() -> None:
    """Increment the counter for messages that were actually processed.

    This function should be called when a message is actually processed
    (not just marked as processed) to track metrics correctly.
    """
    metrics_service.inc("tool_call.messages.processed")


def increment_skipped_counter() -> None:
    """Increment the counter for messages that were skipped during processing.

    This function should be called when a message is skipped (already processed)
    to track metrics correctly.
    """
    metrics_service.inc("tool_call.messages.skipped")


def process_message_if_needed(message: Any) -> bool:
    """Process a message if it hasn't been processed before.

    This function checks if a message has already been processed. If not,
    it marks the message as processed and increments the appropriate counters.

    Args:
        message: The message to check and potentially process

    Returns:
        True if the message was already processed (skipped), False if it was processed now
    """
    if is_message_processed(message):
        increment_skipped_counter()
        return True  # Message was already processed (skipped)
    else:
        mark_message_processed(message)
        increment_processed_counter()
        return False  # Message was processed now


def find_last_assistant_message(messages: list[Any]) -> int | None:
    """Find the index of the last assistant message in a list of messages.

    This function scans the message list from end to start to efficiently
    locate the most recent assistant message. This is useful as a fallback
    strategy when processing markers are not present - typically only the
    last assistant message contains new tool calls that need processing.

    Args:
        messages: List of messages to search. Each message can be a dict
                 or an object with a 'role' attribute.

    Returns:
        The index of the last assistant message, or None if no assistant
        message is found.

    Examples:
        >>> messages = [
        ...     {"role": "user", "content": "Hello"},
        ...     {"role": "assistant", "content": "Hi there"},
        ...     {"role": "user", "content": "How are you?"},
        ...     {"role": "assistant", "content": "I'm good"}
        ... ]
        >>> find_last_assistant_message(messages)
        3
    """
    if not messages:
        return None

    # Scan from end to start for efficiency
    for i in range(len(messages) - 1, -1, -1):
        message = messages[i]
        role = _get_message_role(message)
        if role == "assistant":
            return i

    return None


def _get_message_role(message: Any) -> str | None:
    """Extract the role from a message (dict or object).

    Args:
        message: The message to extract role from.

    Returns:
        The role string, or None if not found.
    """
    if isinstance(message, dict):
        return message.get("role")
    return getattr(message, "role", None)
