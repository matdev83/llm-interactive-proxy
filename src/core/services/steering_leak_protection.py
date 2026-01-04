"""
Steering Leak Protection Service.

This module provides systemic protection against internal steering message leaks
in client-facing responses. It acts as a final safety net to ensure internal
proxy data structures never reach clients.

The protection works by:
1. Detecting patterns that indicate internal steering/replacement responses
2. Scanning both streaming chunks and non-streaming responses
3. Redacting or removing leaked content while preserving valid response data
4. Logging warnings for monitoring and debugging
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SanitizationResult:
    """Result of content sanitization.

    Attributes:
        content: The sanitized content string.
        had_leak: True if a leak was detected and removed, False otherwise.
    """

    content: str
    had_leak: bool


@dataclass(frozen=True)
class BytesSanitizationResult:
    """Result of byte data sanitization.

    Attributes:
        data: The sanitized bytes.
        had_leak: True if a leak was detected and removed, False otherwise.
    """

    data: bytes
    had_leak: bool


@dataclass(frozen=True)
class DictSanitizationResult:
    """Result of dictionary sanitization.

    Attributes:
        data: The sanitized dictionary.
        had_leak: True if internal keys were found and removed, False otherwise.
    """

    data: dict[str, Any]
    had_leak: bool


# Patterns that indicate internal steering data has leaked into client responses
# These patterns should NEVER appear in client-facing content
_STEERING_LEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    # chatcmpl-steering-* ID pattern from replacement responses
    re.compile(r'"id"\s*:\s*"chatcmpl-steering-[^"]+"'),
    # Steering message metadata keys
    re.compile(r'"steering_message"\s*:\s*"'),
    # Tool call swallowed markers
    re.compile(r'"tool_call_swallowed"\s*:\s*true', re.IGNORECASE),
    # Swallowed tool calls array
    re.compile(r'"swallowed_tool_calls"\s*:\s*\['),
    # Swallowed original content marker
    re.compile(r'"swallowed_original_content"\s*:\s*'),
    # Internal replacement markers
    re.compile(r'"replacement_provided"\s*:\s*true', re.IGNORECASE),
    # Steering replacement internal flag
    re.compile(r'"_steering_replacement"\s*:\s*true', re.IGNORECASE),
    # Original tool call embedded in response
    re.compile(r'"original_tool_call"\s*:\s*\{'),
)

# Pattern to extract the leaked JSON structure for removal
# This matches the standard structure including object type
_LEAKED_JSON_PATTERN = re.compile(
    r'\{\s*"id"\s*:\s*"chatcmpl-steering-[^"]+"[^}]*"object"\s*:\s*"chat\.completion"[^}]*\}',
    re.DOTALL,
)

# Simple steering object pattern (e.g. just id and message)
_SIMPLE_STEERING_PATTERN = re.compile(
    r'\{\s*"id"\s*:\s*"chatcmpl-steering-[^"]+"[^}]*\}',
    re.DOTALL,
)

# More aggressive pattern for full steering response structure
_FULL_STEERING_RESPONSE_PATTERN = re.compile(
    r'\{\s*"id"\s*:\s*"chatcmpl-steering-[^"]+".*?"finish_reason"\s*:\s*"stop"\s*\}\s*\]\s*,\s*"usage"\s*:\s*(?:null|\{[^}]*\})\s*\}',
    re.DOTALL,
)


class SteeringLeakProtector:
    """Protects against steering message leaks in outbound responses.

    This class provides methods to detect and sanitize leaked internal
    steering data from client-facing responses. It should be used as a
    final safety net in the response pipeline.

    Usage:
        protector = SteeringLeakProtector()

        # For string content
        result = protector.sanitize_content(content)
        safe_content = result.content

        # For bytes (SSE)
        bytes_result = protector.sanitize_bytes(sse_chunk)
        safe_bytes = bytes_result.data
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        log_leaks: bool = True,
        strict_mode: bool = False,
    ) -> None:
        """Initialize the steering leak protector.

        Args:
            enabled: Whether protection is active. Defaults to True.
            log_leaks: Whether to log detected leaks. Defaults to True.
            strict_mode: If True, raise an error on leak detection instead of
                        just sanitizing. Useful for testing. Defaults to False.
        """
        self._enabled = enabled
        self._log_leaks = log_leaks
        self._strict_mode = strict_mode
        self._leak_count = 0

    @property
    def enabled(self) -> bool:
        """Whether protection is currently enabled."""
        return self._enabled

    @property
    def leak_count(self) -> int:
        """Number of leaks detected since initialization."""
        return self._leak_count

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable protection."""
        self._enabled = enabled

    def has_leak(self, content: str) -> bool:
        """Check if content contains leaked steering data.

        Args:
            content: The content string to check.

        Returns:
            True if leaked steering data is detected, False otherwise.
        """
        if not content:
            return False

        return any(pattern.search(content) for pattern in _STEERING_LEAK_PATTERNS)

    def has_leak_bytes(self, data: bytes) -> bool:
        """Check if byte data contains leaked steering data.

        Args:
            data: The byte data to check.

        Returns:
            True if leaked steering data is detected, False otherwise.
        """
        if not data:
            return False

        try:
            content = data.decode("utf-8", errors="ignore")
            return self.has_leak(content)
        except (AttributeError, TypeError):
            # Handle cases where data is not actually bytes (type hint violation at runtime)
            logger.warning(
                "Failed to decode bytes for leak detection: data type violation",
                exc_info=True,
            )
            return False

    def sanitize_content(self, content: str) -> SanitizationResult:
        """Sanitize content by removing leaked steering data.

        Args:
            content: The content string to sanitize.

        Returns:
            SanitizationResult containing sanitized content and leak detection status.
            If no leak was detected, returns original content unchanged.
        """
        if not self._enabled or not content:
            return SanitizationResult(content=content, had_leak=False)

        if not self.has_leak(content):
            return SanitizationResult(content=content, had_leak=False)

        self._leak_count += 1

        if self._log_leaks:
            # Log a truncated sample of leak for debugging
            sample = content[:500] + "..." if len(content) > 500 else content
            logger.warning(
                "SECURITY: Steering message leak detected in outbound response. "
                "Sanitizing content. Sample: %s",
                sample,
            )

        if self._strict_mode:
            raise SteeringLeakError(
                "Steering message leak detected in strict mode. "
                "This indicates a bug in the response pipeline."
            )

        # Attempt to remove leaked steering response structure
        sanitized = self._remove_leaked_structure(content)

        return SanitizationResult(content=sanitized, had_leak=True)

    def sanitize_bytes(self, data: bytes) -> BytesSanitizationResult:
        """Sanitize byte data by removing leaked steering data.

        Args:
            data: The byte data to sanitize.

        Returns:
            BytesSanitizationResult containing sanitized bytes and leak detection status.
            If no leak was detected, returns original data unchanged.
        """
        if not self._enabled or not data:
            return BytesSanitizationResult(data=data, had_leak=False)

        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            # Can't decode, assume no leak
            return BytesSanitizationResult(data=data, had_leak=False)

        result = self.sanitize_content(content)

        if not result.had_leak:
            return BytesSanitizationResult(data=data, had_leak=False)

        return BytesSanitizationResult(
            data=result.content.encode("utf-8"), had_leak=True
        )

    def sanitize_dict(self, data: dict[str, Any]) -> DictSanitizationResult:
        """Sanitize a dictionary by removing steering-related keys.

        Args:
            data: The dictionary to sanitize.

        Returns:
            DictSanitizationResult containing sanitized dictionary and leak detection status.
        """
        if not self._enabled or not data:
            return DictSanitizationResult(data=data, had_leak=False)

        # Keys that should never appear in client responses
        internal_keys = {
            "steering_message",
            "tool_call_swallowed",
            "swallowed_tool_calls",
            "swallowed_original_content",
            "replacement_provided",
            "_steering_replacement",
            "original_tool_call",
            "tool_call_reactor",
        }

        found_keys = set(data.keys()) & internal_keys
        if not found_keys:
            # Check nested metadata
            metadata = data.get("metadata")
            if isinstance(metadata, dict):
                nested_found = set(metadata.keys()) & internal_keys
                if not nested_found:
                    return DictSanitizationResult(data=data, had_leak=False)
                found_keys = nested_found
            else:
                return DictSanitizationResult(data=data, had_leak=False)

        self._leak_count += 1

        if self._log_leaks:
            logger.warning(
                "SECURITY: Internal steering keys found in outbound response dict. "
                "Keys: %s. Removing.",
                found_keys,
            )

        if self._strict_mode:
            raise SteeringLeakError(
                f"Internal steering keys found in strict mode: {found_keys}"
            )

        # Create a sanitized copy
        sanitized = {k: v for k, v in data.items() if k not in internal_keys}

        # Also sanitize nested metadata
        if "metadata" in sanitized and isinstance(sanitized["metadata"], dict):
            sanitized["metadata"] = {
                k: v for k, v in sanitized["metadata"].items() if k not in internal_keys
            }

        return DictSanitizationResult(data=sanitized, had_leak=True)

    def _remove_leaked_structure(self, content: str) -> str:
        """Remove leaked steering JSON structures from content.

        This method attempts to surgically remove the leaked steering response
        while preserving any legitimate content that may surround it.
        """
        # Try to remove full steering response first
        sanitized = _FULL_STEERING_RESPONSE_PATTERN.sub("", content)

        # If that didn't work, try the simpler pattern
        if sanitized == content:
            sanitized = _LEAKED_JSON_PATTERN.sub("", content)

        # If still no change, try the simplest pattern
        if sanitized == content:
            sanitized = _SIMPLE_STEERING_PATTERN.sub("", content)

        # Clean up any trailing garbage that might remain
        # (e.g., dangling commas, brackets)
        sanitized = sanitized.strip()

        # If we ended up with empty content, provide a safe fallback
        if not sanitized:
            sanitized = "[Response filtered by proxy security]"

        return sanitized


class SteeringLeakError(Exception):
    """Raised when a steering leak is detected in strict mode."""


# Global singleton instance
_global_protector: SteeringLeakProtector | None = None
_global_lock = threading.Lock()


def get_steering_leak_protector() -> SteeringLeakProtector:
    """Get the global steering leak protector instance."""
    global _global_protector
    if _global_protector is None:
        with _global_lock:
            if _global_protector is None:
                _global_protector = SteeringLeakProtector()
    return _global_protector


def set_steering_leak_protector(protector: SteeringLeakProtector | None) -> None:
    """Set the global steering leak protector instance."""
    global _global_protector
    with _global_lock:
        _global_protector = protector


def check_and_sanitize_response(content: str | bytes | dict) -> str | bytes | dict:
    """Convenience function to check and sanitize any response content.

    Args:
        content: The content to check (str, bytes, or dict).

    Returns:
        Sanitized content (str, bytes, or dict). The original type is preserved.
        Use the protector's methods directly if you need to leak detection status.
    """
    protector = get_steering_leak_protector()

    if isinstance(content, str):
        result = protector.sanitize_content(content)
        return result.content
    if isinstance(content, bytes):
        bytes_result = protector.sanitize_bytes(content)
        return bytes_result.data
    if isinstance(content, dict):
        dict_result = protector.sanitize_dict(content)
        return dict_result.data

    # For other types, convert to string and check
    str_content = str(content)
    if protector.has_leak(str_content):
        result = protector.sanitize_content(str_content)
        return result.content

    return str_content
