"""
Retry delay parsing utilities for Gemini API error responses.

This module handles extraction and parsing of retry delay information
from various error response formats including Google RPC RetryInfo,
ErrorInfo, and natural language messages.
"""

import logging
import re
from typing import Any

from src.core.common.exceptions import BackendError

logger = logging.getLogger(__name__)


def parse_duration_string(duration: str) -> float | None:
    """Parse duration string like '10s' or '4h51m33.9s'.

    Args:
        duration: Duration string in formats like:
            - "17493.989s" (simple seconds)
            - "4h51m33.989s" (complex format)

    Returns:
        Duration in seconds as float, or None if parsing failed.
    """
    try:
        # Simple seconds format (e.g. "17493.989s")
        if duration.endswith("s") and "m" not in duration and "h" not in duration:
            return float(duration[:-1])

        # Complex format (e.g. "4h51m33.989s")
        total_seconds = 0.0
        current_val = ""

        for char in duration:
            if char.isdigit() or char == ".":
                current_val += char
            elif char == "h":
                total_seconds += float(current_val) * 3600
                current_val = ""
            elif char == "m":
                total_seconds += float(current_val) * 60
                current_val = ""
            elif char == "s":
                total_seconds += float(current_val)
                current_val = ""

        return total_seconds if total_seconds > 0 else None
    except (ValueError, TypeError):
        return None


def parse_retry_from_message(message: str) -> float | None:
    """Parse retry delay from natural language message.

    Patterns handled:
    - "quota will reset after 46s"
    - "try again in 30 seconds"
    - "wait 1m30s"

    Args:
        message: Error message text

    Returns:
        Retry delay in seconds, or None if not found.
    """
    if not message:
        return None

    def _coerce_unit_multiplier(unit: str) -> float:
        unit_l = unit.lower()
        if unit_l in {"s", "sec", "secs", "second", "seconds"}:
            return 1.0
        if unit_l in {"m", "min", "mins", "minute", "minutes"}:
            return 60.0
        if unit_l in {"h", "hr", "hrs", "hour", "hours"}:
            return 3600.0
        return 1.0

    # Pattern 1: "after X seconds/minutes/hours" or "in X seconds/minutes/hours"
    pattern1 = re.search(
        r"(?:after|in)\s+(\d+(?:\.\d+)?)\s*"
        r"(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)\b",
        message,
        re.IGNORECASE,
    )
    if pattern1:
        try:
            value = float(pattern1.group(1))
            multiplier = _coerce_unit_multiplier(pattern1.group(2))
            return value * multiplier
        except ValueError:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to parse retry delay from pattern1 in message",
                    exc_info=True,
                )

    # Pattern 2: "wait X seconds/minutes/hours"
    pattern2 = re.search(
        r"wait\s+(\d+(?:\.\d+)?)\s*"
        r"(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)?\b",
        message,
        re.IGNORECASE,
    )
    if pattern2:
        try:
            value = float(pattern2.group(1))
            unit = pattern2.group(2) or "s"
            multiplier = _coerce_unit_multiplier(unit)
            return value * multiplier
        except ValueError:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to parse retry delay from pattern2 in message",
                    exc_info=True,
                )

    # Pattern 3: Duration format like "1m30s" or "2m" in the message
    pattern3 = re.search(
        r"\b(\d+m(?:\d+s)?|\d+h(?:\d+m)?(?:\d+s)?)\b",
        message,
        re.IGNORECASE,
    )
    if pattern3:
        parsed = parse_duration_string(pattern3.group(1))
        if parsed is not None:
            return parsed

    return None


def extract_retry_delay(error: BackendError) -> float | None:
    """Extract retry delay from error details.

    Handles:
    1. 'retryDelay' (Google RPC RetryInfo)
    2. 'quotaResetDelay' (Google RPC ErrorInfo metadata)
    3. Natural language in error message (e.g., "quota will reset after 46s")

    Args:
        error: BackendError with details

    Returns:
        Retry delay in seconds, or None if not found.
    """
    if not error.details:
        # Try parsing from error message as last resort
        return parse_retry_from_message(str(error.message or ""))

    # Get the inner error object if present
    error_data = error.details.get("error", error.details)

    # Check details list
    details_list = error_data.get("details")
    if isinstance(details_list, list):
        for detail in details_list:
            if not isinstance(detail, dict):
                continue

            type_url = detail.get("@type", "")

            # Case 1: RetryInfo with retryDelay
            if "RetryInfo" in type_url:
                delay_str = detail.get("retryDelay")
                if isinstance(delay_str, str):
                    parsed = parse_duration_string(delay_str)
                    if parsed is not None:
                        return parsed

            # Case 2: ErrorInfo with quotaResetDelay in metadata
            if "ErrorInfo" in type_url:
                metadata = detail.get("metadata")
                if isinstance(metadata, dict):
                    reset_delay = metadata.get("quotaResetDelay")
                    if isinstance(reset_delay, str):
                        parsed = parse_duration_string(reset_delay)
                        if parsed is not None:
                            return parsed

    # Case 3: Try parsing from the error message text
    message_text = ""
    if isinstance(error_data, dict):
        message_text = error_data.get("message", "")
    if not message_text and error.message:
        message_text = str(error.message)
    if message_text:
        parsed = parse_retry_from_message(message_text)
        if parsed is not None:
            return parsed

    return None


def extract_retry_delay_from_response(
    response_data: dict[str, Any],
) -> float | None:
    """Extract retry delay from a raw response dictionary.

    Args:
        response_data: Raw error response from the API

    Returns:
        Retry delay in seconds, or None if not found.
    """
    error_obj = response_data.get("error", {})
    if not isinstance(error_obj, dict):
        return None

    # Check details in the error object
    details_list = error_obj.get("details", [])
    if isinstance(details_list, list):
        for detail in details_list:
            if not isinstance(detail, dict):
                continue

            type_url = detail.get("@type", "")

            # RetryInfo
            if "RetryInfo" in type_url:
                delay_str = detail.get("retryDelay")
                if isinstance(delay_str, str):
                    return parse_duration_string(delay_str)

            # ErrorInfo with metadata
            if "ErrorInfo" in type_url:
                metadata = detail.get("metadata", {})
                if isinstance(metadata, dict):
                    reset_delay = metadata.get("quotaResetDelay")
                    if isinstance(reset_delay, str):
                        return parse_duration_string(reset_delay)

    # Try parsing from message
    message = error_obj.get("message", "")
    if message:
        return parse_retry_from_message(message)

    return None
