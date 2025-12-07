"""Analysis worker for ProxyMem feature.

Processes the analysis queue and generates summaries for completed sessions.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.memory.config import MemoryConfiguration
    from src.core.memory.service import MemoryService
    from src.core.memory.summary_generator import SummaryGenerator

logger = logging.getLogger(__name__)


class AnalysisWorker:
    """Worker that processes the analysis queue and generates summaries.

    Drains sessions from the MemoryService analysis queue, constructs
    SessionData objects, and calls SummaryGenerator to create and persist
    summaries.
    """

    def __init__(
        self,
        memory_service: MemoryService,
        summary_generator: SummaryGenerator,
        config: MemoryConfiguration,
    ):
        """Initialize the analysis worker.

        Args:
            memory_service: The memory service with the analysis queue.
            summary_generator: The generator for creating summaries.
            config: Memory configuration.
        """
        self._memory_service = memory_service
        self._summary_generator = summary_generator
        self._config = config
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._semaphore: asyncio.Semaphore | None = None

    async def start(self) -> None:
        """Start the analysis worker."""
        if self._running:
            logger.warning("Analysis worker already running")
            return

        self._running = True
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent_analyses)

        # Start worker task
        task = asyncio.create_task(self._worker_loop(), name="memory_analysis_worker")
        self._tasks.append(task)
        logger.info(
            "Started analysis worker (max_concurrent=%d, timeout=%ds)",
            self._config.max_concurrent_analyses,
            self._config.analysis_timeout_seconds,
        )

    async def stop(self) -> None:
        """Stop the analysis worker."""
        self._running = False

        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        self._tasks.clear()
        logger.info("Stopped analysis worker")

    async def _worker_loop(self) -> None:
        """Main worker loop that processes the analysis queue."""
        while self._running:
            try:
                # Get next session from queue
                session_id = await self._memory_service.get_pending_analysis_session()

                if session_id is None:
                    # Queue is empty, wait before checking again
                    await asyncio.sleep(1.0)
                    continue

                # Process with semaphore for concurrency control
                if self._semaphore:
                    async with self._semaphore:
                        await self._process_session(session_id)
                else:
                    await self._process_session(session_id)

            except asyncio.CancelledError:
                logger.debug("Analysis worker loop cancelled")
                raise
            except Exception as e:
                logger.exception("Error in analysis worker loop: %s", e)
                await asyncio.sleep(1.0)  # Avoid tight loop on errors

    async def _process_session(self, session_id: str) -> None:
        """Process a single session for summary generation.

        Args:
            session_id: The session identifier to process.
        """
        logger.debug("Processing session %s for summary generation", session_id)

        try:
            # Get session state
            state = await self._memory_service.get_session_state(session_id)
            if state is None:
                logger.warning("Session %s state not found, skipping", session_id)
                await self._memory_service.complete_analysis(session_id)
                return

            # Get captured interactions
            interactions, is_partial = (
                await self._memory_service.get_captured_interactions(session_id)
            )

            # Get deterministic tool events (file edits and git commits)
            file_edits, git_commits = (
                await self._memory_service.get_captured_tool_events(session_id)
            )

            if not interactions:
                logger.debug("No interactions for session %s, skipping", session_id)
                await self._memory_service.complete_analysis(session_id)
                return

            # Apply timeout to summary generation
            try:
                result = await asyncio.wait_for(
                    self._summary_generator.generate_summary(
                        session_id=session_id,
                        user_id=state.user_id,
                        interactions=interactions,
                        tenant_id=state.tenant_id,
                        project_id=state.project_id,
                        project_root=state.project_root,
                        backend_model=state.backend_model,
                        client_agent=state.client_id,
                        is_partial=is_partial,
                        deterministic_file_edits=file_edits,
                        deterministic_git_commits=git_commits,
                    ),
                    timeout=self._config.analysis_timeout_seconds,
                )

                if result.success:
                    logger.info(
                        "Summary generated for session %s (title: %s)",
                        session_id,
                        result.summary.title if result.summary else "N/A",
                    )
                else:
                    logger.warning(
                        "Summary generation failed for session %s: %s",
                        session_id,
                        result.error,
                    )

            except asyncio.TimeoutError:
                logger.warning(
                    "Summary generation timed out for session %s (limit: %ds)",
                    session_id,
                    self._config.analysis_timeout_seconds,
                )

        except Exception as e:
            logger.exception("Error processing session %s: %s", session_id, e)

        finally:
            # Always mark analysis complete to clean up state
            await self._memory_service.complete_analysis(session_id)

    @property
    def is_running(self) -> bool:
        """Check if the worker is running."""
        return self._running

    def get_queue_size(self) -> int:
        """Get the current analysis queue size."""
        return self._memory_service.get_analysis_queue_size()
