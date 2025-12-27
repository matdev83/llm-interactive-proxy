"""Connection activity tracker cleanup scheduler.

This module provides a scheduler that runs periodic cleanup tasks
for the ConnectionActivityTracker to prevent memory leaks from orphaned connections.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.interfaces.activity_tracker_interface import (
        IConnectionActivityTracker,
    )

logger = logging.getLogger(__name__)


class ConnectionTrackerCleanupScheduler:
    """Schedules and runs periodic cleanup tasks for ConnectionActivityTracker.

    This scheduler manages a background task that periodically calls
    cleanup_stale_connections() on the activity tracker to remove orphaned
    connections and prevent unbounded memory growth.

    The scheduler is designed to be fault-tolerant:
    - Errors in cleanup don't affect the main application
    - Failed cleanup attempts are logged but don't stop subsequent attempts
    - The scheduler can be gracefully started and stopped
    """

    def __init__(
        self,
        activity_tracker: IConnectionActivityTracker,
        cleanup_interval_seconds: float = 300.0,  # 5 minutes
    ) -> None:
        """Initialize the connection tracker cleanup scheduler.

        Args:
            activity_tracker: The connection activity tracker to clean up.
            cleanup_interval_seconds: Interval between cleanup runs in seconds.
                Default is 5 minutes, matching the default stale timeout.
        """
        self._activity_tracker = activity_tracker
        self._cleanup_interval = float(cleanup_interval_seconds)
        self._cleanup_task: asyncio.Task[None] | None = None
        self._running = False
        self._shutdown_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        """Return True if the scheduler is currently running."""
        return self._running

    async def start(self) -> None:
        """Start the periodic cleanup task.

        If the scheduler is already running, this is a no-op.
        """
        if self._running:
            logger.warning("Connection tracker cleanup scheduler already running")
            return

        self._running = True
        self._shutdown_event.clear()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(
            "Connection tracker cleanup scheduler started with %.3f second interval",
            self._cleanup_interval,
        )
        # Run one best-effort cleanup immediately so callers/tests don't have to
        # wait a full interval for the first cleanup pass.
        #
        # If `cleanup_stale_connections` is async, defer to the background loop
        # to avoid blocking startup.
        cleanup_method = getattr(
            self._activity_tracker, "cleanup_stale_connections", None
        )
        if cleanup_method is not None and not inspect.iscoroutinefunction(
            cleanup_method
        ):
            self._run_sync_cleanup_best_effort()

        # Yield control so the background task can start promptly (important in tests
        # that advance a fake clock without awaiting in between).
        await asyncio.sleep(0)

    async def stop(self) -> None:
        """Stop the periodic cleanup task.

        This method waits for the current cleanup cycle to complete
        before shutting down. If the scheduler is not running, this is a no-op.
        """
        if not self._running:
            return

        logger.info("Stopping connection tracker cleanup scheduler...")
        self._running = False
        self._shutdown_event.set()

        if self._cleanup_task:
            try:
                self._cleanup_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._cleanup_task
            except Exception as e:
                logger.error("Error while stopping cleanup task: %s", e, exc_info=True)
            finally:
                self._cleanup_task = None

        logger.info("Connection tracker cleanup scheduler stopped")

    async def _cleanup_loop(self) -> None:
        """Background loop that performs periodic cleanup.

        This method runs until the scheduler is stopped. It performs cleanup
        at the configured interval and handles any errors gracefully.
        """
        while self._running and not self._shutdown_event.is_set():
            try:
                # Perform cleanup
                cleaned_count = await self._run_cleanup_once()

                if cleaned_count > 0 and logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Connection tracker cleanup completed: removed %d stale connections",
                        cleaned_count,
                    )
                elif logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Connection tracker cleanup completed: no stale connections found"
                    )

            except Exception as e:
                logger.error(
                    "Error during connection tracker cleanup: %s",
                    e,
                    exc_info=True,
                )

            # Yield control to ensure other tasks can run
            await asyncio.sleep(0)

            # Wait for the next cleanup cycle or shutdown signal
            wait_task = asyncio.create_task(self._shutdown_event.wait())
            sleep_task = asyncio.create_task(asyncio.sleep(self._cleanup_interval))
            done, pending = await asyncio.wait(
                {wait_task, sleep_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for pending_task in pending:
                pending_task.cancel()
            if wait_task in done:
                break

    def _run_sync_cleanup_best_effort(self) -> None:
        try:
            cleaned_count = self._activity_tracker.cleanup_stale_connections()
            if inspect.isawaitable(cleaned_count):
                # Avoid leaking an un-awaited coroutine; the async cleanup loop will
                # handle the async path.
                if inspect.iscoroutine(cleaned_count):
                    cleaned_count.close()
                return
            if (
                cleaned_count
                and int(cleaned_count) > 0
                and logger.isEnabledFor(logging.INFO)
            ):
                logger.info(
                    "Connection tracker cleanup completed: removed %d stale connections",
                    int(cleaned_count),
                )
        except Exception as e:
            logger.error(
                "Error during connection tracker cleanup: %s",
                e,
                exc_info=True,
            )

    async def _run_cleanup_once(self) -> int:
        cleaned_count: Any = self._activity_tracker.cleanup_stale_connections()
        if inspect.isawaitable(cleaned_count):
            cleaned_count = await cleaned_count
        try:
            return int(cleaned_count or 0)
        except Exception:
            return 0
