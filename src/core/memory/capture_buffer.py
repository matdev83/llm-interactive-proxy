"""Session capture buffer for ProxyMem.

Provides thread-safe buffering of captured interactions per session
with configurable size limits and overflow handling.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.core.memory.models import CapturedInteraction
from src.core.services import metrics_service

logger = logging.getLogger(__name__)

# Default TTL for session buffers (1 hour)
_DEFAULT_SESSION_TTL_SECONDS = 3600

# Default maximum number of session buffers to prevent unbounded growth
_DEFAULT_MAX_SESSIONS = 1000


@dataclass
class SessionBufferState:
    """State for a single session's capture buffer."""

    interactions: list[CapturedInteraction] = field(default_factory=list)
    current_size_bytes: int = 0
    is_partial: bool = False
    overflow_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: float = field(default_factory=time.time)


class SessionCaptureBuffer:
    """Thread-safe buffer for capturing session interactions.

    Maintains separate buffers per session with size limits and overflow handling.
    Implements TTL-based cleanup and max sessions limit to prevent memory leaks.
    """

    def __init__(
        self,
        max_buffer_size_bytes: int = 10 * 1024 * 1024,
        session_ttl_seconds: int = _DEFAULT_SESSION_TTL_SECONDS,
        max_sessions: int = _DEFAULT_MAX_SESSIONS,
    ):
        """Initialize the capture buffer.

        Args:
            max_buffer_size_bytes: Maximum buffer size per session in bytes.
                                   Default is 10MB.
            session_ttl_seconds: Time-to-live for session buffers in seconds.
                                Expired buffers are cleaned up automatically.
                                Default is 1 hour (3600 seconds).
            max_sessions: Maximum number of session buffers to keep in memory.
                          When exceeded, oldest buffers are evicted.
                          Default is 1000.
        """
        self._max_buffer_size = max_buffer_size_bytes
        self._session_ttl = session_ttl_seconds
        self._max_sessions = max_sessions
        self._buffers: dict[str, SessionBufferState] = {}
        self._lock = asyncio.Lock()

    async def append(
        self,
        session_id: str,
        interaction: CapturedInteraction,
    ) -> bool:
        """Append an interaction to the session buffer.

        Args:
            session_id: The session identifier.
            interaction: The interaction to append.

        Returns:
            True if the interaction was appended, False if buffer is full.
        """
        interaction_size = self._estimate_size(interaction)

        async with self._lock:
            await self._maybe_cleanup_expired_locked()

            if session_id not in self._buffers:
                # Check if we need to evict old sessions before adding new one
                if len(self._buffers) >= self._max_sessions:
                    await self._evict_oldest_session_locked()

                self._buffers[session_id] = SessionBufferState()

            buffer_state = self._buffers[session_id]
            buffer_state.last_accessed = time.time()

            if (
                buffer_state.current_size_bytes + interaction_size
                > self._max_buffer_size
            ):
                buffer_state.is_partial = True
                buffer_state.overflow_count += 1
                metrics_service.inc("memory.capture.buffer_overflow")
                logger.warning(
                    "Buffer overflow for session %s: size=%d, max=%d, overflow_count=%d",
                    session_id,
                    buffer_state.current_size_bytes,
                    self._max_buffer_size,
                    buffer_state.overflow_count,
                )
                return False

            buffer_state.interactions.append(interaction)
            buffer_state.current_size_bytes += interaction_size
            metrics_service.inc("memory.capture.buffer_append")
            metrics_service.inc(
                "memory.capture.buffer_bytes_sample", buffer_state.current_size_bytes
            )
            return True

    async def get_and_clear(
        self, session_id: str
    ) -> tuple[list[CapturedInteraction], bool]:
        """Get all interactions for a session and clear the buffer.

        Args:
            session_id: The session identifier.

        Returns:
            Tuple of (interactions list, is_partial flag).
        """
        async with self._lock:
            if session_id not in self._buffers:
                return [], False

            buffer_state = self._buffers.pop(session_id)
            return buffer_state.interactions, buffer_state.is_partial

    async def get_buffer_size(self, session_id: str) -> int:
        """Get the current buffer size in bytes for a session.

        Args:
            session_id: The session identifier.

        Returns:
            Current buffer size in bytes, 0 if session not found.
        """
        async with self._lock:
            await self._maybe_cleanup_expired_locked()
            if session_id not in self._buffers:
                return 0
            buffer_state = self._buffers[session_id]
            buffer_state.last_accessed = time.time()
            return buffer_state.current_size_bytes

    async def get_interaction_count(self, session_id: str) -> int:
        """Get the number of captured interactions for a session.

        Args:
            session_id: The session identifier.

        Returns:
            Number of interactions, 0 if session not found.
        """
        async with self._lock:
            await self._maybe_cleanup_expired_locked()
            if session_id not in self._buffers:
                return 0
            buffer_state = self._buffers[session_id]
            buffer_state.last_accessed = time.time()
            return len(buffer_state.interactions)

    async def is_partial(self, session_id: str) -> bool:
        """Check if a session's buffer is marked as partial (overflow occurred).

        Args:
            session_id: The session identifier.

        Returns:
            True if overflow occurred, False otherwise.
        """
        async with self._lock:
            await self._maybe_cleanup_expired_locked()
            if session_id not in self._buffers:
                return False
            buffer_state = self._buffers[session_id]
            buffer_state.last_accessed = time.time()
            return buffer_state.is_partial

    async def has_session(self, session_id: str) -> bool:
        """Check if a session has a buffer.

        Args:
            session_id: The session identifier.

        Returns:
            True if session has a buffer, False otherwise.
        """
        async with self._lock:
            await self._maybe_cleanup_expired_locked()
            return session_id in self._buffers

    async def clear_session(self, session_id: str) -> None:
        """Clear the buffer for a session without returning data.

        Args:
            session_id: The session identifier.
        """
        async with self._lock:
            self._buffers.pop(session_id, None)

    async def get_active_session_count(self) -> int:
        """Get the number of active session buffers.

        Returns:
            Number of active session buffers.
        """
        async with self._lock:
            await self._maybe_cleanup_expired_locked()
            return len(self._buffers)

    async def _maybe_cleanup_expired_locked(self) -> None:
        """Lazy cleanup: remove expired buffers if any exist.

        This is called automatically on every access to ensure expired buffers
        are cleaned up even when processing stops, preventing memory leaks.
        Must be called with lock held.
        """
        if not self._buffers:
            return

        now = time.time()
        expired = []
        for session_id, state in self._buffers.items():
            if now - state.last_accessed > self._session_ttl:
                expired.append((session_id, now - state.last_accessed))

        for session_id, age in expired:
            self._buffers.pop(session_id, None)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Removed expired session buffer: %s (age: %.1fs)",
                    session_id,
                    age,
                )

    async def _evict_oldest_session_locked(self) -> None:
        """Evict the oldest session buffer when max_sessions limit is reached.

        Must be called with lock held.
        """
        if not self._buffers:
            return

        # Find session with oldest last_accessed time
        oldest_session_id = min(
            self._buffers.items(), key=lambda x: x[1].last_accessed
        )[0]
        self._buffers.pop(oldest_session_id, None)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Evicted oldest session buffer: %s (max_sessions=%d reached)",
                oldest_session_id,
                self._max_sessions,
            )

    def _estimate_size(self, interaction: CapturedInteraction) -> int:
        """Estimate the size of an interaction in bytes.

        Args:
            interaction: The interaction to estimate.

        Returns:
            Estimated size in bytes.
        """
        size = len(interaction.content.encode("utf-8"))
        size += len(interaction.role)
        if interaction.metadata:
            # Optimize: avoid repeated str() conversions
            for key, value in interaction.metadata.items():
                size += len(key)
                if not isinstance(value, str):
                    size += len(str(value))
                else:
                    size += len(value)
        return size
