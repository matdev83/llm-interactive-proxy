"""
StopChunkWithUsage domain model.

This module contains the StopChunkWithUsage class and UsageChunkLeakError,
which provide protection against accidental stringification and JSON serialization
of usage-bearing stop chunks.

These are pure domain models with no transport or vendor dependencies.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.common.exceptions import LLMProxyError

logger = logging.getLogger(__name__)

__all__ = ["StopChunkWithUsage", "UsageChunkLeakError"]


class UsageChunkLeakError(LLMProxyError):
    """Raised when code attempts to stringify a usage chunk dict directly.

    This error indicates a bug where the streaming pipeline is treating
    a usage-bearing stop chunk as plain content instead of preserving
    its OpenAI-format structure for proper SSE serialization.
    """

    def __init__(self, chunk_id: str | None = None) -> None:
        msg = (
            "Attempted to stringify a StopChunkWithUsage directly. "
            "This chunk should be serialized via to_bytes() with proper OpenAI format, "
            "not converted to a plain string. "
            f"Chunk ID: {chunk_id or 'unknown'}"
        )
        super().__init__(message=msg, code=500)


class StopChunkWithUsage(dict):
    """A dict subclass that prevents accidental stringification and JSON serialization.

    This class wraps the final stop chunk dict (containing usage data) and
    raises an error if anyone attempts to:
    - Convert it to string via str()
    - Serialize it via json.dumps() directly
    - Interpolate it in an f-string or % formatting

    The only valid way to serialize this is through StreamingContent.to_bytes()
    which handles it as an OpenAI-format chunk, or by explicitly converting to
    a plain dict first.

    Usage:
        stop_chunk = StopChunkWithUsage({
            "id": "chatcmpl-xxx",
            "choices": [...],
            "usage": {...}
        })
        # These will raise UsageChunkLeakError:
        str(stop_chunk)
        f"Content: {stop_chunk}"
        json.dumps(stop_chunk)  # Raises TypeError

        # This is the correct way (handled by to_bytes()):
        json.dumps(dict(stop_chunk))  # Explicitly convert to plain dict first
        # Or use the safe_json_dumps static method:
        StopChunkWithUsage.safe_json_dumps(stop_chunk)
    """

    _stringify_allowed: bool = False

    def __str__(self) -> str:
        """Raise error on string conversion unless explicitly allowed."""
        if self._stringify_allowed:
            return super().__repr__()
        raise UsageChunkLeakError(chunk_id=self.get("id"))

    def __repr__(self) -> str:
        """Safe repr for debugging - shows it's a protected chunk."""
        return f"<StopChunkWithUsage id={self.get('id')} usage={self.get('usage')}>"

    def items(self):
        """Override items() to prevent json.dumps() from serializing directly.

        This makes json.dumps(StopChunkWithUsage) raise a TypeError, forcing
        callers to explicitly convert to dict first via dict(chunk) or
        chunk.to_plain_dict().

        Note: We override items() because that's what json.dumps() calls when
        serializing dict-like objects.
        """
        raise TypeError(
            f"Cannot directly serialize StopChunkWithUsage (id={dict.get(self, 'id', 'unknown')}). "
            "Convert to plain dict first using dict(chunk) or chunk.to_plain_dict(), "
            "or use StopChunkWithUsage.safe_json_dumps(chunk)."
        )

    def allow_stringify(self) -> StopChunkWithUsage:
        """Temporarily allow stringification (for legitimate serialization).

        Returns self to allow chaining like: json.dumps(chunk.allow_stringify())
        But prefer using dict(chunk) for explicit conversion.
        """
        self._stringify_allowed = True
        return self

    def to_plain_dict(self) -> dict[str, Any]:
        """Convert to a plain dict for safe serialization.

        This is the safe way to get the data when you need to serialize it.
        Returns a true plain dict (not a subclass).
        """
        # Use dict() constructor to ensure we return a plain dict, not a subclass
        return dict(self)

    @staticmethod
    def safe_json_dumps(obj: Any, **kwargs: Any) -> str:
        """Safely serialize any object to JSON, converting StopChunkWithUsage to plain dict.

        This method checks if the object is a StopChunkWithUsage and converts it
        to a plain dict before calling json.dumps(). This prevents accidental
        stringification that would trigger UsageChunkLeakError.

        Args:
            obj: The object to serialize to JSON
            **kwargs: Additional arguments to pass to json.dumps()

        Returns:
            JSON string representation of the object
        """
        if isinstance(obj, StopChunkWithUsage):
            return json.dumps(dict(obj), **kwargs)
        return json.dumps(obj, **kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StopChunkWithUsage:
        """Create a StopChunkWithUsage from a plain dict.

        This is the inverse of to_plain_dict() and enables round-trip
        serialization/deserialization.

        Args:
            data: A dictionary containing the chunk data

        Returns:
            A new StopChunkWithUsage instance

        Raises:
            ValueError: If data is not a dict
        """
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")
        instance = cls(data)
        # Log creation at TRACE level for diagnostic tracking
        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(
                TRACE_LEVEL,
                "[STREAMING] StopChunkWithUsage.from_dict: Created instance, "
                "chunk_id=%s, has_usage=%s, usage=%s",
                data.get("id", "unknown"),
                "usage" in data,
                data.get("usage"),
            )
        return instance

    @classmethod
    def wrap(cls, chunk: dict[str, Any]) -> StopChunkWithUsage:
        """Wrap a dict as a StopChunkWithUsage if it has usage data.

        Args:
            chunk: A dict that may contain usage data

        Returns:
            StopChunkWithUsage if chunk has usage, otherwise returns original dict
        """
        if isinstance(chunk, cls):
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    "[STREAMING] StopChunkWithUsage.wrap: Already wrapped, chunk_id=%s",
                    chunk.get("id", "unknown"),
                )
            return chunk
        if isinstance(chunk, dict) and chunk.get("usage") and chunk.get("choices"):
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    "[STREAMING] StopChunkWithUsage.wrap: Wrapping chunk with usage, "
                    "chunk_id=%s, usage=%s",
                    chunk.get("id", "unknown"),
                    chunk.get("usage"),
                )
            return cls(chunk)
        return chunk  # type: ignore[return-value]
