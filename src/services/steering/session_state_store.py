"""Session state store with TTL and LRU eviction for steering policies."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _SessionEntry:
    """Internal state entry for a session."""

    last_seen: float
    payload: dict[str, Any]


class SessionStateStore:
    """Async-safe TTL + LRU session state store for steering policies.

    Features:
    - Per-session state buckets isolated by session_id
    - TTL eviction on access (lazy) and optional periodic pruning
    - LRU eviction when max_sessions exceeded
    - Thread-safe for async operations (uses asyncio.Lock)

    Configuration:
    - ttl_seconds: Time-to-live for session entries (default: 1800 = 30 minutes)
    - max_sessions: Maximum number of sessions before LRU eviction (default: 1024)
    """

    def __init__(
        self,
        ttl_seconds: int = 1800,
        max_sessions: int = 1024,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        """Initialize session state store.

        Args:
            ttl_seconds: TTL for session entries (minimum 1 second)
            max_sessions: Maximum number of sessions (minimum 1)
            monotonic: Time source for testing (defaults to time.monotonic)
        """
        self._ttl_seconds = max(ttl_seconds, 1)
        self._max_sessions = max(max_sessions, 1)
        self._monotonic = monotonic or time.monotonic
        self._sessions: dict[str, _SessionEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, session_id: str, key: str, default: Any = None) -> Any:
        """Get a value from session state.

        Args:
            session_id: Session identifier
            key: State key within session bucket
            default: Default value if key not found

        Returns:
            The stored value or default if not found/expired
        """
        async with self._lock:
            entry = self._sessions.get(session_id)
            if not entry:
                return default

            now = self._monotonic()
            entry.last_seen = now
            return entry.payload.get(key, default)

    async def set(self, session_id: str, key: str, value: Any) -> None:
        """Set a value in session state.

        Args:
            session_id: Session identifier
            key: State key within session bucket
            value: Value to store
        """
        async with self._lock:
            now = self._monotonic()
            entry = self._sessions.get(session_id)
            if not entry:
                entry = _SessionEntry(last_seen=now, payload={})
                self._sessions[session_id] = entry

            entry.last_seen = now
            entry.payload[key] = value

            self._enforce_max_sessions()

    async def delete(self, session_id: str, key: str | None = None) -> None:
        """Delete a key or entire session from state.

        Args:
            session_id: Session identifier
            key: State key to delete (if None, deletes entire session)
        """
        async with self._lock:
            if key is None:
                self._sessions.pop(session_id, None)
            else:
                entry = self._sessions.get(session_id)
                if entry:
                    entry.payload.pop(key, None)
                    if not entry.payload:
                        del self._sessions[session_id]

    async def update(
        self,
        session_id: str,
        key: str,
        callback: Callable[[Any], Any],
        default: Any = None,
    ) -> Any:
        """Atomically update a value in session state.

        Args:
            session_id: Session identifier
            key: State key
            callback: Function receiving current value (or default) and returning new value
            default: Default value if key missing

        Returns:
            The new value
        """
        async with self._lock:
            now = self._monotonic()
            entry = self._sessions.get(session_id)
            if not entry:
                entry = _SessionEntry(last_seen=now, payload={})
                self._sessions[session_id] = entry

            entry.last_seen = now
            current_value = entry.payload.get(key, default)
            new_value = callback(current_value)
            entry.payload[key] = new_value

            self._enforce_max_sessions()
            return new_value

    async def prune(self) -> int:
        """Manually trigger pruning of expired sessions.

        Returns:
            Number of sessions removed
        """
        async with self._lock:
            now = self._monotonic()
            return self._prune_expired(now)

    def _prune_expired(self, now: float) -> int:
        """Remove expired sessions (lazy eviction on access).

        Args:
            now: Current monotonic time

        Returns:
            Number of sessions removed
        """
        expired = [
            sid
            for sid, entry in self._sessions.items()
            if now - entry.last_seen > self._ttl_seconds
        ]

        for session_id in expired:
            del self._sessions[session_id]

        return len(expired)

    def _enforce_max_sessions(self) -> None:
        """Enforce max_sessions limit using LRU eviction."""
        if len(self._sessions) <= self._max_sessions:
            return

        sorted_sessions = sorted(
            self._sessions.items(), key=lambda item: item[1].last_seen
        )
        remove_count = len(self._sessions) - self._max_sessions

        for session_id, _ in sorted_sessions[:remove_count]:
            del self._sessions[session_id]

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "LRU eviction: removed %d sessions (current: %d, max: %d)",
                remove_count,
                len(self._sessions),
                self._max_sessions,
            )


__all__ = ["SessionStateStore"]
