"""Session capture buffer for ProxyMem.

Provides thread-safe buffering of captured interactions per session
with configurable size limits and overflow handling.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.core.memory.models import CapturedInteraction

logger = logging.getLogger(__name__)


@dataclass
class SessionBufferState:
    """State for a single session's capture buffer."""

    interactions: list[CapturedInteraction] = field(default_factory=list)
    current_size_bytes: int = 0
    is_partial: bool = False
    overflow_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SessionCaptureBuffer:
    """Thread-safe buffer for capturing session interactions.

    Maintains separate buffers per session with size limits and overflow handling.
    """

    def __init__(self, max_buffer_size_bytes: int = 10 * 1024 * 1024):
        """Initialize the capture buffer.

        Args:
            max_buffer_size_bytes: Maximum buffer size per session in bytes.
                                   Default is 10MB.
        """
        self._max_buffer_size = max_buffer_size_bytes
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
            if session_id not in self._buffers:
                self._buffers[session_id] = SessionBufferState()

            buffer_state = self._buffers[session_id]

            if (
                buffer_state.current_size_bytes + interaction_size
                > self._max_buffer_size
            ):
                buffer_state.is_partial = True
                buffer_state.overflow_count += 1
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
            if session_id not in self._buffers:
                return 0
            return self._buffers[session_id].current_size_bytes

    async def get_interaction_count(self, session_id: str) -> int:
        """Get the number of captured interactions for a session.

        Args:
            session_id: The session identifier.

        Returns:
            Number of interactions, 0 if session not found.
        """
        async with self._lock:
            if session_id not in self._buffers:
                return 0
            return len(self._buffers[session_id].interactions)

    async def is_partial(self, session_id: str) -> bool:
        """Check if a session's buffer is marked as partial (overflow occurred).

        Args:
            session_id: The session identifier.

        Returns:
            True if overflow occurred, False otherwise.
        """
        async with self._lock:
            if session_id not in self._buffers:
                return False
            return self._buffers[session_id].is_partial

    async def has_session(self, session_id: str) -> bool:
        """Check if a session has a buffer.

        Args:
            session_id: The session identifier.

        Returns:
            True if session has a buffer, False otherwise.
        """
        async with self._lock:
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
            return len(self._buffers)

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
            for key, value in interaction.metadata.items():
                size += len(key) + len(str(value))
        return size
