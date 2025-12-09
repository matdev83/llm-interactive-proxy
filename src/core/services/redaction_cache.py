"""
Redaction cache for tracking processed messages per session.

This module provides a caching mechanism to avoid reprocessing historical
messages that have already been checked for API key redaction and command
filtering on previous requests in the same session.

Since conversation history messages are immutable (only new messages are
appended), we can safely skip redaction for messages we've already processed.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Maximum number of sessions to track (prevents unbounded memory growth)
_MAX_SESSIONS = 1000

# Session TTL in seconds (1 hour) - cleanup stale entries
_SESSION_TTL_SECONDS = 3600


@dataclass
class SessionRedactionState:
    """Tracks redaction state for a single session."""

    # Set of content hashes that have been processed
    processed_hashes: set[str] = field(default_factory=set)

    # Timestamp of last access (for TTL cleanup)
    last_access: float = field(default_factory=time.time)

    # Number of messages processed (for logging/debugging)
    total_processed: int = 0


class RedactionCache:
    """
    Cache for tracking which messages have been processed for redaction.

    Uses content hashing to identify messages. This handles edge cases like:
    - Message content changes (will be reprocessed)
    - Session resets (new hashes, old ones cleaned up)
    - Different message counts (hash-based, not index-based)
    """

    def __init__(
        self,
        max_sessions: int = _MAX_SESSIONS,
        session_ttl_seconds: float = _SESSION_TTL_SECONDS,
    ) -> None:
        self._states: dict[str, SessionRedactionState] = {}
        self._max_sessions = max_sessions
        self._session_ttl = session_ttl_seconds
        self._lock = threading.Lock()

    def _compute_content_hash(self, content: Any) -> str:
        """Compute a hash of message content for cache lookup.

        Note: MD5 is used here for fast content deduplication, not for security.
        The usedforsecurity=False flag explicitly marks this non-security usage.
        """
        if content is None:
            return "none"

        if isinstance(content, str):
            # Use first 16 chars of MD5 - enough for deduplication
            return hashlib.md5(
                content.encode("utf-8", errors="replace"), usedforsecurity=False
            ).hexdigest()[:16]

        # For list content (multimodal), serialize to string first
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text", "")
                    if text:
                        parts.append(str(text))
                elif hasattr(part, "text"):
                    text = getattr(part, "text", "")
                    if text:
                        parts.append(str(text))
            combined = "||".join(parts)
            return hashlib.md5(
                combined.encode("utf-8", errors="replace"), usedforsecurity=False
            ).hexdigest()[:16]

        # Fallback: convert to string
        return hashlib.md5(
            str(content).encode("utf-8", errors="replace"), usedforsecurity=False
        ).hexdigest()[:16]

    def is_processed(self, session_id: str, content: Any) -> bool:
        """Check if a message content has already been processed."""
        content_hash = self._compute_content_hash(content)

        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                return False

            state.last_access = time.time()
            return content_hash in state.processed_hashes

    def mark_processed(self, session_id: str, content: Any) -> None:
        """Mark a message content as processed."""
        content_hash = self._compute_content_hash(content)

        with self._lock:
            if session_id not in self._states:
                # Check if we need to evict old entries
                self._maybe_cleanup_locked()
                self._states[session_id] = SessionRedactionState()

            state = self._states[session_id]
            state.processed_hashes.add(content_hash)
            state.last_access = time.time()
            state.total_processed += 1

    def get_unprocessed_indices(
        self, session_id: str, messages: list[Any]
    ) -> list[int]:
        """
        Get indices of messages that haven't been processed yet.

        This is the main entry point for optimization: instead of processing
        all messages, only process those at the returned indices.
        """
        unprocessed = []

        with self._lock:
            state = self._states.get(session_id)

            for idx, message in enumerate(messages):
                content = None
                if isinstance(message, dict):
                    content = message.get("content")
                else:
                    content = getattr(message, "content", None)

                content_hash = self._compute_content_hash(content)

                if state is None or content_hash not in state.processed_hashes:
                    unprocessed.append(idx)

        return unprocessed

    def mark_batch_processed(self, session_id: str, messages: list[Any]) -> None:
        """Mark multiple messages as processed at once."""
        with self._lock:
            if session_id not in self._states:
                self._maybe_cleanup_locked()
                self._states[session_id] = SessionRedactionState()

            state = self._states[session_id]
            for message in messages:
                content = None
                if isinstance(message, dict):
                    content = message.get("content")
                else:
                    content = getattr(message, "content", None)

                content_hash = self._compute_content_hash(content)
                if content_hash not in state.processed_hashes:
                    state.processed_hashes.add(content_hash)
                    state.total_processed += 1

            state.last_access = time.time()

    def _maybe_cleanup_locked(self) -> None:
        """Clean up stale sessions if we're at capacity. Must be called with lock held."""
        if len(self._states) < self._max_sessions:
            return

        now = time.time()
        expired_sessions = [
            sid
            for sid, state in self._states.items()
            if now - state.last_access > self._session_ttl
        ]

        for sid in expired_sessions:
            del self._states[sid]

        # If still at capacity after TTL cleanup, evict oldest
        if len(self._states) >= self._max_sessions:
            oldest_session = min(self._states.items(), key=lambda x: x[1].last_access)[
                0
            ]
            del self._states[oldest_session]
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    f"Evicted oldest redaction cache entry for session {oldest_session}"
                )

    def clear_session(self, session_id: str) -> None:
        """Clear cached state for a session."""
        with self._lock:
            self._states.pop(session_id, None)

    def get_stats(self, session_id: str) -> dict[str, Any]:
        """Get statistics for a session's redaction cache."""
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                return {"cached_hashes": 0, "total_processed": 0}
            return {
                "cached_hashes": len(state.processed_hashes),
                "total_processed": state.total_processed,
            }


# Global singleton instance
_global_cache: RedactionCache | None = None
_cache_lock = threading.Lock()


def get_global_redaction_cache() -> RedactionCache:
    """Get the global redaction cache instance."""
    global _global_cache
    if _global_cache is None:
        with _cache_lock:
            if _global_cache is None:
                _global_cache = RedactionCache()
    return _global_cache


def reset_global_redaction_cache() -> None:
    """Reset the global cache (for testing)."""
    global _global_cache
    with _cache_lock:
        _global_cache = None
