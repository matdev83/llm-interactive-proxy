"""Session completion handler for ProxyMem feature.

Detects session completion and triggers summary generation.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.interfaces.memory_service_interface import IMemoryService
    from src.core.memory.config import MemoryConfiguration

    _ = IMemoryService  # vulture: ignore

logger = logging.getLogger(__name__)


class SessionCompletionDetector:
    """Detects session completion based on timeout and explicit close."""

    def __init__(
        self,
        memory_service: IMemoryService,
        config: MemoryConfiguration,
    ):
        """Initialize the completion detector.

        Args:
            memory_service: The memory service.
            config: Memory configuration.
        """
        self._memory_service = memory_service
        self._config = config
        self._last_activity: dict[str, float] = {}
        self._completed_sessions: set[str] = set()
        self._cleanup_task: asyncio.Task | None = None
        self._running = False

    def record_activity(self, session_id: str) -> None:
        """Record activity for a session.

        Args:
            session_id: The session identifier.
        """
        if session_id not in self._completed_sessions:
            self._last_activity[session_id] = time.time()

    async def on_session_close(
        self,
        session_id: str,
        *,
        backend_model: str | None = None,
        branch: str | None = None,
        head_sha: str | None = None,
    ) -> None:
        """Handle explicit session close.

        Args:
            session_id: The session identifier.
            backend_model: Optional backend:model used.
            branch: Optional git branch.
            head_sha: Optional git HEAD SHA.
        """
        if session_id in self._completed_sessions:
            return

        if not self._memory_service.is_available():
            return

        if not await self._memory_service.is_enabled_for_session(session_id):
            return

        await self._complete_session(
            session_id,
            backend_model=backend_model,
            branch=branch,
            head_sha=head_sha,
        )

    async def start_timeout_checker(self) -> None:
        """Start the timeout check background task."""
        if self._running:
            return

        self._running = True
        self._cleanup_task = asyncio.create_task(self._timeout_check_loop())
        logger.info("Started session timeout checker")

    async def stop_timeout_checker(self) -> None:
        """Stop the timeout check background task."""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None
        logger.info("Stopped session timeout checker")

    async def _timeout_check_loop(self) -> None:
        """Check for timed-out sessions periodically."""
        check_interval = 60  # Check every minute
        while self._running:
            try:
                await self._check_timeouts()
            except Exception as e:
                logger.exception("Timeout check failed: %s", e)

            await asyncio.sleep(check_interval)

    async def _check_timeouts(self) -> None:
        """Check for sessions that have exceeded timeout."""
        now = time.time()
        timeout_seconds = self._config.session_timeout_minutes * 60

        timed_out = []
        for session_id, last_activity in list(self._last_activity.items()):
            if session_id in self._completed_sessions:
                continue

            if now - last_activity > timeout_seconds:
                timed_out.append(session_id)

        for session_id in timed_out:
            if await self._memory_service.is_enabled_for_session(session_id):
                logger.info("Session %s timed out, completing...", session_id)
                await self._complete_session(session_id)

    async def _complete_session(
        self,
        session_id: str,
        *,
        backend_model: str | None = None,
        branch: str | None = None,
        head_sha: str | None = None,
    ) -> None:
        """Mark a session as complete.

        Args:
            session_id: The session identifier.
            backend_model: Optional backend:model used.
            branch: Optional git branch.
            head_sha: Optional git HEAD SHA.
        """
        if session_id in self._completed_sessions:
            return

        self._completed_sessions.add(session_id)
        self._last_activity.pop(session_id, None)

        await self._memory_service.mark_session_complete(
            session_id,
            backend_model=backend_model,
            branch=branch,
            head_sha=head_sha,
        )

    def clear_session(self, session_id: str) -> None:
        """Clear tracking for a session.

        Args:
            session_id: The session identifier.
        """
        self._last_activity.pop(session_id, None)
        self._completed_sessions.discard(session_id)
