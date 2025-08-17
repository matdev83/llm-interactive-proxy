from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI

from src.core.interfaces.session_service import ISessionService

logger = logging.getLogger(__name__)


class AppLifecycle:
    """Handles application lifecycle events.

    This class manages startup and shutdown tasks for the application.
    """

    def __init__(self, app: FastAPI, config: dict[str, Any]):
        """Initialize the lifecycle manager.

        Args:
            app: The FastAPI application
            config: The application configuration
        """
        self.app = app
        self.config = config
        self._background_tasks: list[asyncio.Task] = []

    async def startup(self) -> None:
        """Perform startup tasks.

        This method is called during application startup.
        """
        logger.info("Starting application lifecycle...")

        # Start background tasks
        self._start_background_tasks()

    async def shutdown(self) -> None:
        """Perform shutdown tasks.

        This method is called during application shutdown.
        """
        logger.info("Shutting down application lifecycle...")

        # Stop background tasks
        await self._stop_background_tasks()

        # Close any remaining connections
        await self._close_connections()

    def _start_background_tasks(self) -> None:
        """Start background tasks."""
        # Start session cleanup task
        if self.config.get("session_cleanup_enabled", False):
            interval = self.config.get(
                "session_cleanup_interval", 3600
            )  # 1 hour default
            max_age = self.config.get("session_max_age", 86400)  # 1 day default

            task = asyncio.create_task(
                self._session_cleanup_task(interval, max_age),
                name="session_cleanup",
            )
            self._background_tasks.append(task)
            logger.info(
                f"Started session cleanup task (interval: {interval}s, max age: {max_age}s)"
            )

    async def _stop_background_tasks(self) -> None:
        """Stop background tasks."""
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    logger.info(f"Cancelled background task: {task.get_name()}")

    async def _close_connections(self) -> None:
        """Close any remaining connections."""
        # Any connection cleanup code would go here

    async def _session_cleanup_task(self, interval: int, max_age: int) -> None:
        """Background task for cleaning up expired sessions.

        Args:
            interval: The interval in seconds between cleanup runs
            max_age: The maximum age in seconds for sessions
        """
        try:
            while True:
                await asyncio.sleep(interval)

                try:
                    # Get service provider
                    provider = self.app.state.service_provider
                    if not provider:
                        logger.warning(
                            "Service provider not available for session cleanup"
                        )
                        continue

                    # Get session service
                    session_service = provider.get_service(ISessionService)
                    if not session_service:
                        logger.warning("Session service not available for cleanup")
                        continue

                    # Perform cleanup
                    deleted_count = 0
                    if hasattr(session_service, "cleanup_expired_sessions"):
                        deleted_count = await session_service.cleanup_expired_sessions(
                            max_age
                        )

                    if deleted_count > 0:
                        logger.info(f"Cleaned up {deleted_count} expired sessions")

                except Exception as e:
                    logger.error(f"Error during session cleanup: {e!s}")

        except asyncio.CancelledError:
            logger.debug("Session cleanup task cancelled")
            raise
