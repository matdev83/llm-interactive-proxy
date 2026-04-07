"""Canonical retry-after extraction helper for resilience flows."""

from __future__ import annotations

import contextlib
import email.utils
import math
import re
import time
from collections.abc import Mapping
from typing import Any

_MESSAGE_AFTER_OR_IN_RE = re.compile(
    r"(?:after|in)\s+(\d+(?:\.\d+)?)\s*"
    r"(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)\b",
    re.IGNORECASE,
)
_MESSAGE_WAIT_RE = re.compile(
    r"wait\s+(\d+(?:\.\d+)?)\s*"
    r"(seconds?|secs?|sec|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)?\b",
    re.IGNORECASE,
)
_MESSAGE_DURATION_RE = re.compile(
    r"\b(\d+h(?:\d+m)?(?:\d+(?:\.\d+)?s)?|\d+m(?:\d+(?:\.\d+)?s)?|\d+(?:\.\d+)?s)\b",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"^\s*"
    r"(?:(?P<hours>\d+(?:\.\d+)?)h)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)m)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)s)?"
    r"\s*$",
    re.IGNORECASE,
)


def _normalize_seconds(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    with contextlib.suppress(TypeError, ValueError):
        seconds = float(value)
        if math.isfinite(seconds) and seconds >= 0:
            return seconds
    return None


def _parse_duration_string(duration: Any) -> float | None:
    if not isinstance(duration, str):
        return None

    stripped = duration.strip()
    if not stripped:
        return None

    direct_seconds = _normalize_seconds(stripped)
    if direct_seconds is not None:
        return direct_seconds

    match = _DURATION_RE.match(stripped)
    if not match:
        return None

    components = match.groupdict()
    if not any(components.values()):
        return None

    total_seconds = 0.0
    for key, multiplier in (
        ("hours", 3600.0),
        ("minutes", 60.0),
        ("seconds", 1.0),
    ):
        value = components.get(key)
        if value is None:
            continue
        with contextlib.suppress(TypeError, ValueError):
            total_seconds += float(value) * multiplier

    return total_seconds if total_seconds >= 0 else None


def _parse_retry_after_header(value: Any) -> float | None:
    parsed = _normalize_seconds(value)
    if parsed is not None:
        return parsed

    if not isinstance(value, str):
        return None

    with contextlib.suppress(TypeError, ValueError, OverflowError):
        parsed_date = email.utils.parsedate_to_datetime(value)
        seconds = parsed_date.timestamp() - time.time()
        return max(0.0, seconds)
    return None


def _headers_get(headers: Mapping[Any, Any], key: str) -> Any:
    for candidate in (key, key.lower(), key.upper(), key.title()):
        if candidate in headers:
            return headers[candidate]
    lower_key = key.lower()
    for header_key, header_value in headers.items():
        if isinstance(header_key, str) and header_key.lower() == lower_key:
            return header_value
    return None


def _extract_from_headers(headers: Mapping[Any, Any]) -> float | None:
    for key in ("retry-after", "retry_after", "retryAfter"):
        parsed = _parse_retry_after_header(_headers_get(headers, key))
        if parsed is not None:
            return parsed
    return None


def _extract_google_retry_after(details: Mapping[str, Any]) -> float | None:
    def _yield_detail_objects(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        objects: list[dict[str, Any]] = []
        candidates: list[Any] = []
        if isinstance(payload.get("details"), list):
            candidates.extend(payload["details"])
        nested_error = payload.get("error")
        if isinstance(nested_error, Mapping) and isinstance(
            nested_error.get("details"), list
        ):
            candidates.extend(nested_error["details"])
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                objects.append(dict(candidate))
        return objects

    for detail in _yield_detail_objects(details):
        retry_delay = _parse_duration_string(detail.get("retryDelay"))
        if retry_delay is not None:
            return retry_delay

        metadata = detail.get("metadata")
        if isinstance(metadata, Mapping):
            for metadata_key in (
                "quotaResetDelay",
                "retryDelay",
                "retry_after_seconds",
                "retry_after",
                "retryAfter",
            ):
                retry_delay = _parse_duration_string(
                    _headers_get(metadata, metadata_key)
                )
                if retry_delay is not None:
                    return retry_delay

    return None


def _extract_from_details(details: Mapping[str, Any]) -> float | None:
    for key in ("retry_after_seconds", "retry_after", "retryAfter"):
        parsed = _normalize_seconds(_headers_get(details, key))
        if parsed is not None:
            return parsed

    headers = details.get("headers")
    if isinstance(headers, Mapping):
        parsed = _extract_from_headers(headers)
        if parsed is not None:
            return parsed

    parsed = _extract_google_retry_after(details)
    if parsed is not None:
        return parsed

    return None


def _extract_from_reset_at(error: Exception) -> float | None:
    reset_at = _normalize_seconds(getattr(error, "reset_at", None))
    if reset_at is None:
        return None

    now = time.time()
    if reset_at >= now or reset_at > 1e9:
        return max(0.0, reset_at - now)
    return reset_at


def _duration_multiplier(unit: str) -> float:
    unit_l = unit.lower()
    if unit_l in {"s", "sec", "secs", "second", "seconds"}:
        return 1.0
    if unit_l in {"m", "min", "mins", "minute", "minutes"}:
        return 60.0
    if unit_l in {"h", "hr", "hrs", "hour", "hours"}:
        return 3600.0
    return 1.0


def _extract_from_message(message: str) -> float | None:
    if not message:
        return None

    match_after_or_in = _MESSAGE_AFTER_OR_IN_RE.search(message)
    if match_after_or_in:
        value = _normalize_seconds(match_after_or_in.group(1))
        if value is not None:
            return value * _duration_multiplier(match_after_or_in.group(2))

    match_wait = _MESSAGE_WAIT_RE.search(message)
    if match_wait:
        value = _normalize_seconds(match_wait.group(1))
        if value is not None:
            unit = match_wait.group(2) or "s"
            return value * _duration_multiplier(unit)

    match_duration = _MESSAGE_DURATION_RE.search(message)
    if match_duration:
        parsed_duration = _parse_duration_string(match_duration.group(1))
        if parsed_duration is not None:
            return parsed_duration

    return None


def _collect_message_candidates(
    error: Exception, details: Mapping[str, Any] | None
) -> list[str]:
    candidates: list[str] = []

    message_attr = getattr(error, "message", None)
    if isinstance(message_attr, str) and message_attr.strip():
        candidates.append(message_attr)

    if isinstance(details, Mapping):
        detail_message = _headers_get(details, "message")
        if isinstance(detail_message, str) and detail_message.strip():
            candidates.append(detail_message)

        nested_error = details.get("error")
        if isinstance(nested_error, Mapping):
            nested_message = _headers_get(nested_error, "message")
            if isinstance(nested_message, str) and nested_message.strip():
                candidates.append(nested_message)

    error_str = str(error)
    if error_str.strip():
        candidates.append(error_str)

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(candidates))


def extract_retry_after_seconds(error: Exception) -> float | None:
    """Extract a conservative retry-after hint in seconds from known error shapes."""
    from_reset_at = _extract_from_reset_at(error)
    if from_reset_at is not None:
        return from_reset_at

    from_attr = _normalize_seconds(getattr(error, "retry_after", None))
    if from_attr is not None:
        return from_attr

    details = getattr(error, "details", None)
    if isinstance(details, Mapping):
        from_details = _extract_from_details(details)
        if from_details is not None:
            return from_details

    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if isinstance(headers, Mapping):
        from_headers = _extract_from_headers(headers)
        if from_headers is not None:
            return from_headers

    for message in _collect_message_candidates(
        error, details if isinstance(details, Mapping) else None
    ):
        from_message = _extract_from_message(message)
        if from_message is not None:
            return from_message

    return None


__all__ = ["extract_retry_after_seconds"]
