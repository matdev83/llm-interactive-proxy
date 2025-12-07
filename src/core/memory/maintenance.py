"""Database maintenance for ProxyMem feature.

Provides retention cleanup and database optimization tasks.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from src.core.memory.config import MemoryConfiguration

if TYPE_CHECKING:
    from src.core.memory.repository import IMemoryRepository

logger = logging.getLogger(__name__)


class DatabaseMaintenance:
    """Handles database maintenance tasks for ProxyMem."""

    def __init__(
        self,
        config: MemoryConfiguration,
        repository: IMemoryRepository,
    ):
        """Initialize database maintenance.

        Args:
            config: Memory configuration.
            repository: Repository for database operations.
        """
        self._config = config
        self._repository = repository
        self._running = False
        self._task: asyncio.Task | None = None

    async def run_cleanup(self) -> int:
        """Run retention-based cleanup.

        Deletes sessions older than the configured retention period.

        Returns:
            Number of sessions deleted.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=self._config.retention_days
        )
        deleted = await self._repository.delete_old_sessions(cutoff)

        if deleted > 0:
            logger.info(
                "Retention cleanup: deleted %d sessions older than %d days",
                deleted,
                self._config.retention_days,
            )

        return deleted

    async def start_periodic_cleanup(
        self,
        interval_hours: int = 24,
    ) -> None:
        """Start periodic cleanup task.

        Args:
            interval_hours: Hours between cleanup runs.
        """
        if self._running:
            logger.warning("Periodic cleanup already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop(interval_hours))
        logger.info("Started periodic cleanup with %d hour interval", interval_hours)

    async def stop_periodic_cleanup(self) -> None:
        """Stop periodic cleanup task."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("Stopped periodic cleanup")

    async def _cleanup_loop(self, interval_hours: int) -> None:
        """Periodic cleanup loop.

        Args:
            interval_hours: Hours between cleanup runs.
        """
        while self._running:
            try:
                await self.run_cleanup()
            except Exception as e:
                logger.exception("Cleanup task failed: %s", e)

            # Sleep until next run
            await asyncio.sleep(interval_hours * 3600)

    @property
    def is_running(self) -> bool:
        """Check if periodic cleanup is running."""
        return self._running
