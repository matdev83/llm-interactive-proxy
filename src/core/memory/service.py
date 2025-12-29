"""Core memory service implementation for ProxyMem."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from weakref import WeakSet

import pydantic

from src.core.memory.capture_buffer import SessionCaptureBuffer
from src.core.memory.config import MemoryConfiguration
from src.core.memory.models import (
    CapturedInteraction,
    FileEditEvent,
    GitCommitEvent,
    ToolEvent,
)
from src.core.memory.tool_event_collector import DeterministicToolEventCollector
from src.core.services import metrics_service

if TYPE_CHECKING:
    from src.core.memory.repository import IMemoryRepository

logger = logging.getLogger(__name__)


class RequeueResult(pydantic.BaseModel):
    """Result of requeue_session_summary operation.

    Attributes:
        success: Whether the session was successfully requeued
        message: Human-readable status message
    """

    success: bool
    message: str

    model_config = {"frozen": True}


# Maximum number of session states to keep in memory to prevent unbounded growth.
# 10,000 sessions is roughly ~2-3 MB of memory, providing a large window
# for active sessions without unbounded growth. Eviction uses LRU policy.
_MAX_SESSION_STATES = 10_000

# TTL for session states: remove if not accessed for 1 hour
# This prevents accumulation of stale sessions that were never completed or disabled
_SESSION_STATE_TTL_SECONDS = 3600

# TTL for analysis_in_progress entries: remove if stuck for 30 minutes
# This prevents accumulation of sessions stuck in analysis if worker crashes
_ANALYSIS_IN_PROGRESS_TTL_SECONDS = 1800

# Maximum number of analysis_in_progress entries to prevent unbounded growth
# If entries are added faster than they expire, this limit prevents memory leaks
# 5,000 entries is roughly ~200 KB of memory (assuming ~40 bytes per entry)
_MAX_ANALYSIS_IN_PROGRESS = 5_000


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
    last_access: float = field(default_factory=time.time)  # For TTL-based cleanup


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
        # Use OrderedDict for LRU eviction to prevent unbounded memory growth
        self._session_states: OrderedDict[str, SessionMemoryState] = OrderedDict()
        self._state_lock = asyncio.Lock()
        self._analysis_lock = asyncio.Lock()  # Lock for _analysis_in_progress access
        self._analysis_queue: asyncio.Queue[str] = asyncio.Queue(
            maxsize=config.analysis_queue_maxsize
        )
        # Track when sessions entered analysis_in_progress for TTL cleanup
        self._analysis_in_progress: dict[str, float] = {}
        # Track cleanup tasks to prevent resource leaks
        # Use WeakSet to allow garbage collection of completed tasks, preventing unbounded accumulation
        # Tasks are kept alive by done callbacks until completion, then automatically removed
        self._cleanup_tasks: WeakSet[asyncio.Task[None]] = WeakSet()

    def is_available(self) -> bool:
        """Check if memory feature is globally available."""
        return self._config.available

    async def is_enabled_for_session(self, session_id: str) -> bool:
        """Check if memory is enabled for a specific session."""
        async with self._state_lock:
            if session_id in self._session_states:
                # Update last access time and move to end (LRU)
                state = self._session_states[session_id]
                state.last_access = time.time()
                self._session_states.move_to_end(session_id)
                await self._maybe_cleanup_stale_sessions_locked()
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
            metrics_service.inc("memory.sessions.enable_unavailable")
            return False

        # Check single-user mode
        if self._config.single_user_mode:
            user_id = self._config.fixed_user_id or "default-user"
        elif not user_id:
            logger.warning("Missing user_id in multi-user mode, failing closed")
            metrics_service.inc("memory.sessions.enable_missing_user")
            return False

        # Check user deny list
        if user_id in self._config.disabled_users:
            logger.debug("User %s is in deny list", user_id)
            metrics_service.inc("memory.sessions.enable_denied_user")
            return False

        # Check client deny list
        if client_id and client_id in self._config.disabled_clients:
            logger.debug("Client %s is in deny list", client_id)
            metrics_service.inc("memory.sessions.enable_denied_client")
            return False

        # Check project discovery gating
        if self._config.require_project_discovery and not project_root:
            logger.debug("Project root required but not available")
            metrics_service.inc("memory.sessions.enable_missing_project")
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

            # Check if we need to evict old sessions before adding new one
            await self._maybe_cleanup_stale_sessions_locked()
            # Enforce max limit by evicting oldest sessions if needed
            while len(self._session_states) >= _MAX_SESSION_STATES:
                await self._evict_oldest_session_locked()

            self._session_states[session_id] = SessionMemoryState(
                user_id=user_id,
                tenant_id=tenant_id,
                client_id=client_id,
                project_root=project_root,
                project_id=project_id,
            )
            # Move to end (most recently used) for LRU tracking
            self._session_states.move_to_end(session_id)

            metrics_service.inc("memory.sessions.enabled")
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
                metrics_service.inc("memory.capture.skipped")
                return False

        result = await self._capture_buffer.append(session_id, interaction)
        if not result:
            logger.warning(
                "Buffer overflow for session %s, marking as partial",
                session_id,
            )
            metrics_service.inc("memory.capture.buffer_full")
        else:
            metrics_service.inc("memory.capture.appended")
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
            # Update last access time and move to end (LRU)
            state.last_access = time.time()
            self._session_states.move_to_end(session_id)
            project_root = state.project_root

        await self._tool_event_collector.record_tool_event(
            session_id, event, project_root
        )
        return True

    async def requeue_session_summary(self, session_id: str) -> RequeueResult:
        """Force a session back into the analysis queue."""
        if not self.is_available():
            return RequeueResult(
                success=False, message="Memory feature is not available."
            )

        async with self._state_lock:
            if session_id not in self._session_states:
                return RequeueResult(
                    success=False, message="Session is not enabled for memory."
                )
            state = self._session_states[session_id]
            state.last_access = time.time()
            self._session_states.move_to_end(session_id)
            state.queued_for_analysis = True

        interaction_count = await self._capture_buffer.get_interaction_count(session_id)
        if interaction_count == 0:
            metrics_service.inc("memory.analysis.requeue_empty")
            return RequeueResult(
                success=False, message="No buffered interactions to summarize."
            )

        try:
            self._analysis_queue.put_nowait(session_id)
            metrics_service.inc("memory.analysis.requeued")
            return RequeueResult(
                success=True, message="Session queued for summary regeneration."
            )
        except asyncio.QueueFull:
            metrics_service.inc("memory.analysis.queue_full")
            return RequeueResult(
                success=False, message="Analysis queue is full; try again later."
            )

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
            # Update last access time and move to end (LRU)
            state.last_access = time.time()
            self._session_states.move_to_end(session_id)
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
            metrics_service.inc("memory.analysis.queued_delayed")
            logger.info(
                "Session %s scheduled for summary in %d seconds",
                session_id,
                self._config.summarization_delay_seconds,
            )
        else:
            # Immediate summarization for delay=0 (backwards compatibility)
            try:
                self._analysis_queue.put_nowait(session_id)
                metrics_service.inc("memory.analysis.queued")
                logger.info("Session %s queued for analysis immediately", session_id)
            except asyncio.QueueFull:
                metrics_service.inc("memory.analysis.queue_full")
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
            if state:
                # Update last access time and move to end (LRU)
                state.last_access = time.time()
                self._session_states.move_to_end(session_id)
            return state.user_id if state else None

    async def get_session_project_root(self, session_id: str) -> str | None:
        """Get the project root associated with a session."""
        async with self._state_lock:
            state = self._session_states.get(session_id)
            if state:
                # Update last access time and move to end (LRU)
                state.last_access = time.time()
                self._session_states.move_to_end(session_id)
            return state.project_root if state else None

    async def get_session_state(self, session_id: str) -> SessionMemoryState | None:
        """Get the full session state."""
        async with self._state_lock:
            state = self._session_states.get(session_id)
            if state:
                # Update last access time and move to end (LRU)
                state.last_access = time.time()
                self._session_states.move_to_end(session_id)
            return state

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
            metrics_service.inc("memory.analysis.dequeued")
            # Clean up stale entries before adding new one
            await self._cleanup_stale_analysis_in_progress()
            # Track when session entered analysis_in_progress for TTL cleanup
            # Enforce max limit to prevent unbounded growth
            async with self._analysis_lock:
                if len(self._analysis_in_progress) >= _MAX_ANALYSIS_IN_PROGRESS:
                    # If still at limit, evict oldest entries (by timestamp)
                    sorted_entries = sorted(
                        self._analysis_in_progress.items(), key=lambda x: x[1]
                    )
                    excess_count = (
                        len(self._analysis_in_progress) - _MAX_ANALYSIS_IN_PROGRESS + 1
                    )
                    for sid, _ in sorted_entries[:excess_count]:
                        self._analysis_in_progress.pop(sid, None)
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Evicted %d oldest analysis_in_progress entries (max=%d reached)",
                            excess_count,
                            _MAX_ANALYSIS_IN_PROGRESS,
                        )
                self._analysis_in_progress[session_id] = time.time()
            return session_id
        except asyncio.QueueEmpty:
            # Still clean up stale entries even if queue is empty
            await self._cleanup_stale_analysis_in_progress()
            return None

    async def complete_analysis(self, session_id: str) -> None:
        """Mark analysis as complete for a session."""
        async with self._analysis_lock:
            self._analysis_in_progress.pop(session_id, None)
        metrics_service.inc("memory.analysis.completed")

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
                metrics_service.inc("memory.analysis.queued")
                logger.info("Session %s queued for delayed analysis", session_id)
            except asyncio.QueueFull:
                metrics_service.inc("memory.analysis.queue_full")
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

    async def get_buffered_session_count(self) -> int:
        """Get the number of sessions with active capture buffers."""
        return await self._capture_buffer.get_active_session_count()

    async def cleanup(self) -> None:
        """Clean up pending cleanup tasks to prevent resource leaks.

        This method awaits all pending cleanup tasks created during session
        eviction. Should be called during application shutdown to ensure
        all resources (HTTP connections, file handles, etc.) are properly released.
        """
        # Take snapshot of pending tasks
        pending_tasks = [t for t in self._cleanup_tasks if not t.done()]
        if pending_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending_tasks, return_exceptions=True),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                # Cancel tasks that didn't complete in time
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Timeout waiting for MemoryService cleanup tasks, cancelling"
                    )
                for task in pending_tasks:
                    if not task.done():
                        task.cancel()
                # Await cancelled tasks to ensure they complete
                with contextlib.suppress(Exception):
                    await asyncio.gather(*pending_tasks, return_exceptions=True)
            except Exception:
                # If gather fails, cancel all tasks
                logger.warning(
                    "Error during MemoryService cleanup task gather",
                    exc_info=True,
                )
                for task in pending_tasks:
                    if not task.done():
                        task.cancel()
                with contextlib.suppress(Exception):
                    await asyncio.gather(
                        *pending_tasks, return_exceptions=True
                    )  # Suppress errors during final cleanup

        # Clear the cleanup tasks set to prevent memory leaks
        self._cleanup_tasks.clear()

    async def _maybe_cleanup_stale_sessions_locked(self) -> None:
        """Clean up stale session states based on TTL.

        Must be called with _state_lock held.
        """
        now = time.time()
        expired_sessions = [
            sid
            for sid, state in self._session_states.items()
            if now - state.last_access > _SESSION_STATE_TTL_SECONDS
        ]

        for sid in expired_sessions:
            state = self._session_states.get(sid)
            if state:
                # Cancel any pending summary task
                if state.summary_task and not state.summary_task.done():
                    state.summary_task.cancel()
                # Remove from session states
                del self._session_states[sid]
                # Also remove from analysis_in_progress if present
                async with self._analysis_lock:
                    self._analysis_in_progress.pop(sid, None)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Removed stale session state: %s (last access: %.1fs ago)",
                        sid,
                        now - state.last_access,
                    )
                # Clear buffers to free memory
                # Note: We can't await here since we're in a locked context,
                # so we schedule cleanup tasks and track them to prevent resource leaks
                cleanup_task1 = asyncio.create_task(
                    self._capture_buffer.clear_session(sid)
                )
                cleanup_task2 = asyncio.create_task(
                    self._tool_event_collector.clear_session(sid)
                )
                # Add done callbacks to remove tasks from WeakSet when they complete
                # This prevents unbounded accumulation while allowing GC after completion
                cleanup_task1.add_done_callback(
                    lambda task: self._cleanup_tasks.discard(task)
                )
                cleanup_task2.add_done_callback(
                    lambda task: self._cleanup_tasks.discard(task)
                )
                self._cleanup_tasks.add(cleanup_task1)
                self._cleanup_tasks.add(cleanup_task2)

    async def _evict_oldest_session_locked(self) -> None:
        """Evict the oldest session state when max limit is reached (LRU eviction).

        Must be called with _state_lock held.
        """
        if not self._session_states:
            return

        # Get oldest entry (first in OrderedDict)
        oldest_session_id, oldest_state = next(iter(self._session_states.items()))

        # Cancel any pending summary task
        if oldest_state.summary_task and not oldest_state.summary_task.done():
            oldest_state.summary_task.cancel()

        # Remove from session states
        del self._session_states[oldest_session_id]
        # Also remove from analysis_in_progress if present
        async with self._analysis_lock:
            self._analysis_in_progress.pop(oldest_session_id, None)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Evicted oldest session state: %s (max_sessions=%d reached)",
                oldest_session_id,
                _MAX_SESSION_STATES,
            )

        # Clear buffers to free memory
        # Note: We can't await here since we're in a locked context,
        # so we schedule cleanup tasks and track them to prevent resource leaks
        cleanup_task1 = asyncio.create_task(
            self._capture_buffer.clear_session(oldest_session_id)
        )
        cleanup_task2 = asyncio.create_task(
            self._tool_event_collector.clear_session(oldest_session_id)
        )
        # Add done callbacks to remove tasks from WeakSet when they complete
        # This prevents unbounded accumulation while allowing GC after completion
        cleanup_task1.add_done_callback(lambda task: self._cleanup_tasks.discard(task))
        cleanup_task2.add_done_callback(lambda task: self._cleanup_tasks.discard(task))
        self._cleanup_tasks.add(cleanup_task1)
        self._cleanup_tasks.add(cleanup_task2)

    async def _cleanup_stale_analysis_in_progress(self) -> None:
        """Clean up stale entries from _analysis_in_progress based on TTL.

        This prevents accumulation of sessions stuck in analysis if worker crashes.
        """
        now = time.time()
        async with self._analysis_lock:
            expired_sessions = [
                (sid, timestamp)
                for sid, timestamp in self._analysis_in_progress.items()
                if now - timestamp > _ANALYSIS_IN_PROGRESS_TTL_SECONDS
            ]

            for sid, timestamp in expired_sessions:
                self._analysis_in_progress.pop(sid, None)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Removed stale analysis_in_progress entry: %s (stuck for %.1fs)",
                        sid,
                        now - timestamp,
                    )
