"""Core memory service implementation for ProxyMem."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.core.memory.capture_buffer import SessionCaptureBuffer
from src.core.memory.config import MemoryConfiguration
from src.core.memory.models import (
    CapturedInteraction,
    FileEditEvent,
    GitCommitEvent,
    ToolEvent,
)
from src.core.memory.tool_event_collector import DeterministicToolEventCollector

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
    summary_task: asyncio.Task | None = (
        None  # Background task for delayed summarization
    )


class MemoryService:
    """Core memory service managing session capture and context retrieval.

    Implements IMemoryService protocol for managing cross-session context.
    """

    def __init__(
        self,
        config: MemoryConfiguration,
        repository: IMemoryRepository,
        capture_buffer: SessionCaptureBuffer | None = None,
        tool_event_collector: DeterministicToolEventCollector | None = None,
    ):
        """Initialize the memory service.

        Args:
            config: Memory configuration.
            repository: Repository for persisting summaries.
            capture_buffer: Optional capture buffer (created if not provided).
            tool_event_collector: Optional tool event collector (created if not provided).
        """
        self._config = config
        self._repository = repository
        self._capture_buffer = capture_buffer or SessionCaptureBuffer(
            max_buffer_size_bytes=config.max_buffer_size_bytes
        )
        self._tool_event_collector = (
            tool_event_collector or DeterministicToolEventCollector()
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

        # Cancel any pending summary task if session is being resumed
        async with self._state_lock:
            if session_id in self._session_states:
                existing_state = self._session_states[session_id]
                if (
                    existing_state.summary_task
                    and not existing_state.summary_task.done()
                ):
                    existing_state.summary_task.cancel()
                    logger.debug(
                        "Cancelled pending summary task for resumed session %s",
                        session_id,
                    )

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

            return True

    async def disable_for_session(self, session_id: str) -> None:
        """Disable memory capture for a session."""
        async with self._state_lock:
            if session_id in self._session_states:
                state = self._session_states[session_id]
                # Cancel any pending summary task
                if state.summary_task and not state.summary_task.done():
                    state.summary_task.cancel()
                del self._session_states[session_id]
                logger.debug("Memory disabled for session %s", session_id)

        # Clear the capture buffer and tool events without returning data
        await self._capture_buffer.clear_session(session_id)
        await self._tool_event_collector.clear_session(session_id)

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

    async def record_tool_event(
        self,
        session_id: str,
        event: ToolEvent,
    ) -> bool:
        """Record a deterministic tool event (file edit or git commit).

        Events are only recorded when memory is enabled for the session.
        File paths are normalized relative to the project root when available.

        Args:
            session_id: The session identifier.
            event: The tool event to record.

        Returns:
            True if the event was recorded, False if session not enabled.
        """
        async with self._state_lock:
            if session_id not in self._session_states:
                return False
            state = self._session_states[session_id]
            project_root = state.project_root

        await self._tool_event_collector.record_tool_event(
            session_id, event, project_root
        )
        return True

    async def mark_session_complete(
        self,
        session_id: str,
        *,
        backend_model: str | None = None,
        branch: str | None = None,
        head_sha: str | None = None,
        termination_reason: str | None = None,
    ) -> bool:
        """Mark a session as complete and queue for summary generation after a configurable delay.

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

            # Cancel any existing summary task
            if state.summary_task and not state.summary_task.done():
                state.summary_task.cancel()
                logger.debug(
                    "Cancelled existing summary task for session %s", session_id
                )

            # Update state with backend info
            if backend_model:
                state.backend_model = backend_model

            # Log termination reason if provided (Requirement 5.3, 5.4)
            if termination_reason:
                logger.info(
                    "Session %s completed with termination reason: %s",
                    session_id,
                    termination_reason,
                    extra={
                        "session_id": session_id,
                        "termination_reason": termination_reason,
                    },
                )

            state.queued_for_analysis = True

        # Create background task with configurable delay
        if self._config.summarization_delay_seconds > 0:
            state.summary_task = asyncio.create_task(
                self._delayed_summary(
                    session_id, self._config.summarization_delay_seconds
                )
            )
            logger.info(
                "Session %s scheduled for summary in %d seconds",
                session_id,
                self._config.summarization_delay_seconds,
            )
        else:
            # Immediate summarization for delay=0 (backwards compatibility)
            try:
                self._analysis_queue.put_nowait(session_id)
                logger.info("Session %s queued for analysis immediately", session_id)
            except asyncio.QueueFull:
                logger.warning(
                    "Analysis queue full, dropping session %s (backpressure)",
                    session_id,
                )
                async with self._state_lock:
                    if session_id in self._session_states:
                        self._session_states[session_id].queued_for_analysis = False
                        # Clean up session state to prevent memory leak when queue is persistently full.
                        # The session cannot be processed, so we remove it to prevent unbounded growth.
                        # Buffers are cleared to free memory immediately.
                        state = self._session_states[session_id]
                        # Cancel any pending summary task
                        if state.summary_task and not state.summary_task.done():
                            state.summary_task.cancel()
                        # Remove from session states
                        del self._session_states[session_id]
                # Clear buffers to free memory
                await self._capture_buffer.clear_session(session_id)
                await self._tool_event_collector.clear_session(session_id)
                return False

        return True

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

    async def get_captured_tool_events(
        self, session_id: str
    ) -> tuple[list[FileEditEvent], list[GitCommitEvent]]:
        """Get captured tool events for a session.

        Returns tuple of (file_edits, git_commits).
        Clears the events from the collector after retrieval.
        """
        return await self._tool_event_collector.get_and_clear(session_id)

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

    async def _delayed_summary(self, session_id: str, delay_seconds: int) -> None:
        """Background task to queue delayed session summarization."""
        try:
            await asyncio.sleep(delay_seconds)
            # Check if session still exists and is still queued for analysis
            async with self._state_lock:
                if session_id not in self._session_states:
                    logger.debug(
                        "Session %s no longer exists, skipping delayed summary",
                        session_id,
                    )
                    return
                state = self._session_states[session_id]
                if not state.queued_for_analysis:
                    logger.debug("Session %s no longer queued for analysis", session_id)
                    return

            # Queue for actual analysis processing
            try:
                self._analysis_queue.put_nowait(session_id)
                logger.info("Session %s queued for delayed analysis", session_id)
            except asyncio.QueueFull:
                logger.warning(
                    "Analysis queue full during delayed processing, dropping session %s (backpressure)",
                    session_id,
                )
                async with self._state_lock:
                    if session_id in self._session_states:
                        self._session_states[session_id].queued_for_analysis = False

        except asyncio.CancelledError:
            logger.debug("Delayed summary task cancelled for session %s", session_id)
            raise
        except Exception as e:
            logger.exception(
                "Error in delayed summary task for session %s: %s", session_id, e
            )

    def get_analysis_queue_size(self) -> int:
        """Get the current size of the analysis queue."""
        return self._analysis_queue.qsize()

    def get_active_session_count(self) -> int:
        """Get the number of active memory-enabled sessions."""
        return len(self._session_states)
