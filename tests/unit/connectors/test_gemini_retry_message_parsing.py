"""Tests for retry delay extraction from Gemini error messages."""

from __future__ import annotations

import re


def parse_retry_from_message(message: str) -> float | None:
    """Parse retry delay from natural language message.

    This is a copy of the method from GeminiOAuthBaseConnector
    for isolated unit testing.

    Patterns handled:
    - "quota will reset after 46s"
    - "try again in 30 seconds"
    - "wait 1m30s"
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
            pass

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
            pass

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


def parse_duration_string(duration: str) -> float | None:
    """Parse duration string like '10s' or '4h51m33.9s'."""
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


class TestRetryMessageParsing:
    """Tests for parsing retry delay from error messages."""

    def test_parse_quota_reset_after_seconds(self) -> None:
        """Test parsing 'quota will reset after 46s' message."""
        message = (
            "You have exhausted your capacity on this model. "
            "Your quota will reset after 46s."
        )
        result = parse_retry_from_message(message)
        assert result == 46.0

    def test_parse_try_again_in_seconds(self) -> None:
        """Test parsing 'try again in 30 seconds' message."""
        message = "Rate limit exceeded. Please try again in 30 seconds."
        result = parse_retry_from_message(message)
        assert result == 30.0

    def test_parse_try_again_in_minutes(self) -> None:
        """Test parsing 'try again in 1 minute' message."""
        message = "No capacity available. Try again in 1 minute."
        result = parse_retry_from_message(message)
        assert result == 60.0

    def test_parse_wait_seconds(self) -> None:
        """Test parsing 'wait 15 seconds' message."""
        message = "Too many requests. Please wait 15 seconds before retrying."
        result = parse_retry_from_message(message)
        assert result == 15.0

    def test_parse_duration_in_message(self) -> None:
        """Test parsing duration format in message."""
        message = "Rate limited. Retry in 1m30s."
        result = parse_retry_from_message(message)
        # Falls back to duration pattern matching
        assert result == 90.0  # 1m30s = 90 seconds

    def test_parse_after_decimal_seconds(self) -> None:
        """Test parsing decimal seconds."""
        message = "Quota reset after 45.5s"
        result = parse_retry_from_message(message)
        assert result == 45.5

    def test_no_match_returns_none(self) -> None:
        """Test that unrecognized message returns None."""
        message = "Unknown error occurred."
        result = parse_retry_from_message(message)
        assert result is None

    def test_empty_message_returns_none(self) -> None:
        """Test empty message returns None."""
        result = parse_retry_from_message("")
        assert result is None

    def test_parse_sec_abbreviation(self) -> None:
        """Test parsing 'sec' abbreviation."""
        message = "Try again after 30sec."
        result = parse_retry_from_message(message)
        assert result == 30.0

    def test_case_insensitive(self) -> None:
        """Test case insensitive matching."""
        message = "WAIT 20 SECONDS before retrying."
        result = parse_retry_from_message(message)
        assert result == 20.0
