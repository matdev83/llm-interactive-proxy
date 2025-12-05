from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from fastapi import FastAPI

from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.wire_capture_interface import IWireCapture

logger = logging.getLogger(__name__)


class AppLifecycle:
    """Handles application lifecycle events.

    This class manages startup and shutdown tasks for the application.
    """

    def __init__(self, app: FastAPI, config: dict[str, Any]) -> None:
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
        if logger.isEnabledFor(logging.INFO):
            logger.info("Starting application lifecycle...")

        # Start health check services
        await self._start_health_checks()

        # Start background tasks
        self._start_background_tasks()

    async def shutdown(self) -> None:
        """Perform shutdown tasks.

        This method is called during application shutdown.
        """
        if logger.isEnabledFor(logging.INFO):
            logger.info("Shutting down application lifecycle...")

        # Stop background tasks
        await self._stop_background_tasks()

        # Close any remaining connections
        await self._close_connections()

    async def _start_health_checks(self) -> None:
        """Start health check services if enabled."""
        provider = getattr(self.app.state, "service_provider", None)
        if not provider:
            return

        try:
            from src.core.services.health.backend_notifier import (
                BackendHealthNotifier,
            )
            from src.core.services.health.health_check_scheduler import (
                HealthCheckScheduler,
            )
            from src.core.services.health.logging_handler import HealthLoggingHandler
            from src.core.services.health.state_manager import HealthStateManager

            # Start state manager (subscribes to check events)
            state_manager = provider.get_service(HealthStateManager)
            if state_manager:
                await state_manager.start()

            # Start logging handler (subscribes to transition events)
            logging_handler = provider.get_service(HealthLoggingHandler)
            if logging_handler:
                await logging_handler.start()

            # Start backend notifier (routes health events to backends)
            backend_notifier = provider.get_service(BackendHealthNotifier)
            if backend_notifier:
                await backend_notifier.start()

            # Start scheduler (runs background check loops)
            scheduler = provider.get_service(HealthCheckScheduler)
            if scheduler:
                await scheduler.start()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Health check services started")

        except ImportError:
            # Health check services not available
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Error starting health check services: %s", e)

    def _start_background_tasks(self) -> None:
        """Start background tasks."""
        # Start session cleanup task
        if self.config.get("session_cleanup_enabled", False):
            interval = self.config.get(
                "session_cleanup_interval", 3600
            )  # 1 hour default
            max_age = self.config.get("session_max_age", 86400)  # 1 day default

            task = asyncio.create_task(
                self._session_cleanup_task(interval, max_age), name="session_cleanup"
            )
            self._background_tasks.append(task)
            if logger.isEnabledFor(logging.INFO):
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
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(f"Cancelled background task: {task.get_name()}")

    async def _close_connections(self) -> None:
        """Close any remaining connections."""
        # Get service provider
        provider = getattr(self.app.state, "service_provider", None)
        if not provider:
            return

        # Shutdown health check services
        await self._shutdown_health_checks(provider)

        # Get wire capture service and shut it down
        wire_capture_service = provider.get_service(IWireCapture)
        if wire_capture_service and hasattr(wire_capture_service, "shutdown"):
            await wire_capture_service.shutdown()

    async def _shutdown_health_checks(self, provider: Any) -> None:
        """Shutdown health check services.

        Args:
            provider: The service provider.
        """
        try:
            from src.core.services.health.backend_notifier import (
                BackendHealthNotifier,
            )
            from src.core.services.health.health_check_scheduler import (
                HealthCheckScheduler,
            )
            from src.core.services.health.logging_handler import HealthLoggingHandler
            from src.core.services.health.state_manager import HealthStateManager

            # Stop scheduler first
            scheduler = provider.get_service(HealthCheckScheduler)
            if scheduler:
                await scheduler.shutdown()

            # Stop backend notifier
            backend_notifier = provider.get_service(BackendHealthNotifier)
            if backend_notifier:
                await backend_notifier.stop()

            # Stop state manager
            state_manager = provider.get_service(HealthStateManager)
            if state_manager:
                await state_manager.stop()

            # Stop logging handler
            logging_handler = provider.get_service(HealthLoggingHandler)
            if logging_handler:
                await logging_handler.stop()

            # Shutdown event bus
            from src.core.interfaces.event_bus_interface import IEventBus

            event_bus = provider.get_service(IEventBus)
            if event_bus:
                await event_bus.shutdown()

        except ImportError:
            # Health check services not available
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Error shutting down health check services: %s", e)

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
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Service provider not available for session cleanup"
                            )
                        continue

                    # Get session service
                    session_service = provider.get_service(ISessionService)
                    if not session_service:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning("Session service not available for cleanup")
                        continue

                    # Perform cleanup
                    deleted_count = 0
                    with suppress(AttributeError):
                        deleted_count = await session_service.cleanup_expired(max_age)

                    if deleted_count > 0 and logger.isEnabledFor(logging.INFO):
                        logger.info(f"Cleaned up {deleted_count} expired sessions")

                except Exception as e:
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error(f"Error during session cleanup: {e!s}")

        except asyncio.CancelledError:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Session cleanup task cancelled")
            raise
