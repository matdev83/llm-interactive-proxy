"""Core memory service implementation for ProxyMem."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.core.memory.capture_buffer import SessionCaptureBuffer
from src.core.memory.config import MemoryConfiguration
from src.core.memory.models import CapturedInteraction

if TYPE_CHECKING:
    from src.core.memory.repository import IMemoryRepository

logger = logging.getLogger(__name__)


@dataclass
class SessionMemoryState:
    """State for a memory-enabled session."""

    user_id: str
    tenant_id: str | None = None
    client_id: str | None = None
    project_root: str | None = None
    project_id: str | None = None
    backend_model: str | None = None
    enabled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    queued_for_analysis: bool = False


class MemoryService:
    """Core memory service managing session capture and context retrieval.

    Implements IMemoryService protocol for managing cross-session context.
    """

    def __init__(
        self,
        config: MemoryConfiguration,
        repository: IMemoryRepository,
        capture_buffer: SessionCaptureBuffer | None = None,
    ):
        """Initialize the memory service.

        Args:
            config: Memory configuration.
            repository: Repository for persisting summaries.
            capture_buffer: Optional capture buffer (created if not provided).
        """
        self._config = config
        self._repository = repository
        self._capture_buffer = capture_buffer or SessionCaptureBuffer(
            max_buffer_size_bytes=config.max_buffer_size_bytes
        )
        self._session_states: dict[str, SessionMemoryState] = {}
        self._state_lock = asyncio.Lock()
        self._analysis_queue: asyncio.Queue[str] = asyncio.Queue(
            maxsize=config.analysis_queue_maxsize
        )
        self._analysis_in_progress: set[str] = set()

    def is_available(self) -> bool:
        """Check if memory feature is globally available."""
        return self._config.available

    async def is_enabled_for_session(self, session_id: str) -> bool:
        """Check if memory is enabled for a specific session."""
        async with self._state_lock:
            return session_id in self._session_states

    async def enable_for_session(
        self,
        session_id: str,
        user_id: str,
        *,
        client_id: str | None = None,
        tenant_id: str | None = None,
        project_root: str | None = None,
    ) -> bool:
        """Enable memory capture for a session.

        Returns False if:
        - Memory is globally unavailable
        - User is in deny list
        - Client is in deny list
        - user_id is missing in multi-user mode
        """
        if not self.is_available():
            logger.debug("Memory not available globally")
            return False

        # Check single-user mode
        if self._config.single_user_mode:
            user_id = self._config.fixed_user_id or "default-user"
        elif not user_id:
            logger.warning("Missing user_id in multi-user mode, failing closed")
            return False

        # Check user deny list
        if user_id in self._config.disabled_users:
            logger.debug("User %s is in deny list", user_id)
            return False

        # Check client deny list
        if client_id and client_id in self._config.disabled_clients:
            logger.debug("Client %s is in deny list", client_id)
            return False

        # Check project discovery gating
        if self._config.require_project_discovery and not project_root:
            logger.debug("Project root required but not available")
            return False

        async with self._state_lock:
            if session_id in self._session_states:
                logger.debug("Session %s already has memory enabled", session_id)
                return True

            # Get or create project_id
            project_id = None
            if project_root:
                project_id = await self._repository.get_or_create_project_id(
                    user_id, project_root
                )

            self._session_states[session_id] = SessionMemoryState(
                user_id=user_id,
                tenant_id=tenant_id,
                client_id=client_id,
                project_root=project_root,
                project_id=project_id,
            )

            logger.info(
                "Memory enabled for session %s (user=%s, project=%s)",
                session_id,
                user_id,
                project_id,
            )
            return True

    async def disable_for_session(self, session_id: str) -> None:
        """Disable memory capture for a session."""
        async with self._state_lock:
            if session_id in self._session_states:
                del self._session_states[session_id]
                logger.debug("Memory disabled for session %s", session_id)

        # Clear the capture buffer without returning data
        await self._capture_buffer.clear_session(session_id)

    async def capture_interaction(
        self,
        session_id: str,
        interaction: CapturedInteraction,
    ) -> bool:
        """Capture an interaction for a session.

        Returns False if session not enabled or buffer full.
        """
        async with self._state_lock:
            if session_id not in self._session_states:
                return False

        result = await self._capture_buffer.append(session_id, interaction)
        if not result:
            logger.warning(
                "Buffer overflow for session %s, marking as partial",
                session_id,
            )
        return result

    async def mark_session_complete(
        self,
        session_id: str,
        *,
        backend_model: str | None = None,
        branch: str | None = None,
        head_sha: str | None = None,
    ) -> bool:
        """Mark a session as complete and queue for summary generation.

        Returns False if session not enabled or already queued.
        """
        async with self._state_lock:
            if session_id not in self._session_states:
                logger.debug("Session %s not enabled for memory", session_id)
                return False

            state = self._session_states[session_id]
            if state.queued_for_analysis:
                logger.debug("Session %s already queued for analysis", session_id)
                return False

            # Update state with backend info
            if backend_model:
                state.backend_model = backend_model

            state.queued_for_analysis = True

        # Try to queue for analysis with backpressure
        try:
            self._analysis_queue.put_nowait(session_id)
            logger.info("Session %s queued for analysis", session_id)
            return True
        except asyncio.QueueFull:
            logger.warning(
                "Analysis queue full, dropping session %s (backpressure)",
                session_id,
            )
            async with self._state_lock:
                if session_id in self._session_states:
                    self._session_states[session_id].queued_for_analysis = False
            return False

    async def get_session_user_id(self, session_id: str) -> str | None:
        """Get the user ID associated with a session."""
        async with self._state_lock:
            state = self._session_states.get(session_id)
            return state.user_id if state else None

    async def get_session_project_root(self, session_id: str) -> str | None:
        """Get the project root associated with a session."""
        async with self._state_lock:
            state = self._session_states.get(session_id)
            return state.project_root if state else None

    async def get_session_state(self, session_id: str) -> SessionMemoryState | None:
        """Get the full session state."""
        async with self._state_lock:
            return self._session_states.get(session_id)

    async def get_captured_interactions(
        self, session_id: str
    ) -> tuple[list[CapturedInteraction], bool]:
        """Get captured interactions for a session.

        Returns tuple of (interactions, is_partial).
        """
        return await self._capture_buffer.get_and_clear(session_id)

    async def get_pending_analysis_session(self) -> str | None:
        """Get the next session ID pending analysis.

        Returns None if queue is empty.
        """
        try:
            session_id = self._analysis_queue.get_nowait()
            self._analysis_in_progress.add(session_id)
            return session_id
        except asyncio.QueueEmpty:
            return None

    async def complete_analysis(self, session_id: str) -> None:
        """Mark analysis as complete for a session."""
        self._analysis_in_progress.discard(session_id)

        async with self._state_lock:
            self._session_states.pop(session_id, None)

    def get_analysis_queue_size(self) -> int:
        """Get the current size of the analysis queue."""
        return self._analysis_queue.qsize()

    def get_active_session_count(self) -> int:
        """Get the number of active memory-enabled sessions."""
        return len(self._session_states)
