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

        # Start ProxyMem services (analysis worker, maintenance)
        await self._start_memory_services()

        # Start EoS subscribers
        await self._start_eos_subscribers()

        # Start usage tracking services (async write queue)
        await self._start_usage_tracking_services()

        # Start background tasks
        self._start_background_tasks()

    async def shutdown(self) -> None:
        """Perform shutdown tasks.

        This method is called during application shutdown.
        """
        if logger.isEnabledFor(logging.INFO):
            logger.info("Shutting down application lifecycle...")

        # Stop EoS subscribers
        await self._stop_eos_subscribers()

        # Stop ProxyMem services
        await self._stop_memory_services()

        # Stop usage tracking services (drain pending records)
        await self._stop_usage_tracking_services()

        # Stop background tasks
        await self._stop_background_tasks()

        # Close any remaining connections
        await self._close_connections()

    async def _start_memory_services(self) -> None:
        """Start ProxyMem services (analysis worker, maintenance).

        Per Req 10.2: Start periodic cleanup on proxy startup.
        Per Req 6.6: Start analysis queue processor.
        """
        provider = getattr(self.app.state, "service_provider", None)
        if not provider:
            return

        try:
            from src.core.memory.analysis_worker import AnalysisWorker
            from src.core.memory.completion_detector import SessionCompletionDetector
            from src.core.memory.config import MemoryConfiguration
            from src.core.memory.maintenance import DatabaseMaintenance

            # Check if memory feature is available
            memory_config = provider.get_service(MemoryConfiguration)
            if not memory_config or not memory_config.available:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("ProxyMem not available, skipping service startup")
                return

            # Start analysis worker (processes queue, generates summaries)
            analysis_worker = provider.get_service(AnalysisWorker)
            if analysis_worker:
                await analysis_worker.start()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("ProxyMem analysis worker started")

            # Start session completion detector (timeout checker)
            completion_detector = provider.get_service(SessionCompletionDetector)
            if completion_detector:
                await completion_detector.start_timeout_checker()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("ProxyMem session timeout checker started")

            # Start database maintenance (retention cleanup)
            maintenance = provider.get_service(DatabaseMaintenance)
            if maintenance:
                await maintenance.start_periodic_cleanup(interval_hours=24)
                if logger.isEnabledFor(logging.INFO):
                    logger.info("ProxyMem database maintenance started")

        except ImportError:
            # Memory services not available
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Error starting ProxyMem services: %s", e)

    async def _start_eos_subscribers(self) -> None:
        """Start End-of-Session event subscribers.

        Starts all EoS subscribers that listen for RemoteBackendConnectionEndOfSessionEvent.
        """
        provider = getattr(self.app.state, "service_provider", None)
        if not provider:
            return

        # Start ProxyMemEosSubscriber
        try:
            from src.core.memory.eos_subscriber import ProxyMemEosSubscriber

            subscriber = provider.get_service(ProxyMemEosSubscriber)
            if subscriber:
                await subscriber.start()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("ProxyMemEosSubscriber started")
        except ImportError:
            # ProxyMemEosSubscriber not available (memory disabled)
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Failed to start ProxyMemEosSubscriber: {e}", exc_info=True)

        # Start UsageTrackingEosSubscriber
        try:
            from src.core.services.usage_tracking_eos_subscriber import (
                UsageTrackingEosSubscriber,
            )

            subscriber = provider.get_service(UsageTrackingEosSubscriber)
            if subscriber:
                await subscriber.start()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("UsageTrackingEosSubscriber started")
        except ImportError:
            # UsageTrackingEosSubscriber not available
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to start UsageTrackingEosSubscriber: {e}", exc_info=True
                )

        # Start WireCaptureEosSubscriber
        try:
            from src.core.services.wire_capture_eos_subscriber import (
                WireCaptureEosSubscriber,
            )

            subscriber = provider.get_service(WireCaptureEosSubscriber)
            if subscriber:
                await subscriber.start()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("WireCaptureEosSubscriber started")
        except ImportError:
            # WireCaptureEosSubscriber not available
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to start WireCaptureEosSubscriber: {e}", exc_info=True
                )

        # Start TestExecutionReminderEosSubscriber
        # Note: This subscriber is created inline in provider_lifecycle and stored
        # in provider._test_execution_reminder_eos_subscriber
        try:
            from src.services.test_execution_reminder.eos_subscriber import (
                TestExecutionReminderEosSubscriber,
            )

            # Try to get the subscriber from provider (stored in provider_lifecycle)
            subscriber = getattr(provider, "_test_execution_reminder_eos_subscriber", None)
            if subscriber and isinstance(subscriber, TestExecutionReminderEosSubscriber):
                await subscriber.start()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("TestExecutionReminderEosSubscriber started")
            else:
                # Fallback: try to get from DI if registered as service
                subscriber = provider.get_service(TestExecutionReminderEosSubscriber)
                if subscriber:
                    await subscriber.start()
                    if logger.isEnabledFor(logging.INFO):
                        logger.info("TestExecutionReminderEosSubscriber started")
        except ImportError:
            # TestExecutionReminderEosSubscriber not available
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to start TestExecutionReminderEosSubscriber: {e}",
                    exc_info=True,
                )

    async def _stop_eos_subscribers(self) -> None:
        """Stop End-of-Session event subscribers.

        Stops all EoS subscribers that were started during application startup.
        """
        provider = getattr(self.app.state, "service_provider", None)
        if not provider:
            return

        # Stop ProxyMemEosSubscriber
        try:
            from src.core.memory.eos_subscriber import ProxyMemEosSubscriber

            subscriber = provider.get_service(ProxyMemEosSubscriber)
            if subscriber:
                await subscriber.stop()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("ProxyMemEosSubscriber stopped")
        except ImportError:
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Failed to stop ProxyMemEosSubscriber: {e}", exc_info=True)

        # Stop UsageTrackingEosSubscriber
        try:
            from src.core.services.usage_tracking_eos_subscriber import (
                UsageTrackingEosSubscriber,
            )

            subscriber = provider.get_service(UsageTrackingEosSubscriber)
            if subscriber:
                await subscriber.stop()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("UsageTrackingEosSubscriber stopped")
        except ImportError:
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to stop UsageTrackingEosSubscriber: {e}", exc_info=True
                )

        # Stop WireCaptureEosSubscriber
        try:
            from src.core.services.wire_capture_eos_subscriber import (
                WireCaptureEosSubscriber,
            )

            subscriber = provider.get_service(WireCaptureEosSubscriber)
            if subscriber:
                await subscriber.stop()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("WireCaptureEosSubscriber stopped")
        except ImportError:
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to stop WireCaptureEosSubscriber: {e}", exc_info=True
                )

        # Stop TestExecutionReminderEosSubscriber
        try:
            from src.services.test_execution_reminder.eos_subscriber import (
                TestExecutionReminderEosSubscriber,
            )

            # Try to get the subscriber from provider (stored in provider_lifecycle)
            subscriber = getattr(provider, "_test_execution_reminder_eos_subscriber", None)
            if subscriber and isinstance(subscriber, TestExecutionReminderEosSubscriber):
                await subscriber.stop()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("TestExecutionReminderEosSubscriber stopped")
            else:
                # Fallback: try to get from DI if registered as service
                subscriber = provider.get_service(TestExecutionReminderEosSubscriber)
                if subscriber:
                    await subscriber.stop()
                    if logger.isEnabledFor(logging.INFO):
                        logger.info("TestExecutionReminderEosSubscriber stopped")
        except ImportError:
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to stop TestExecutionReminderEosSubscriber: {e}",
                    exc_info=True,
                )

    async def _stop_memory_services(self) -> None:
        """Stop ProxyMem services."""
        provider = getattr(self.app.state, "service_provider", None)
        if not provider:
            return

        try:
            from src.core.memory.analysis_worker import AnalysisWorker
            from src.core.memory.completion_detector import SessionCompletionDetector
            from src.core.memory.maintenance import DatabaseMaintenance

            # Stop analysis worker
            analysis_worker = provider.get_service(AnalysisWorker)
            if analysis_worker:
                await analysis_worker.stop()

            # Stop session completion detector
            completion_detector = provider.get_service(SessionCompletionDetector)
            if completion_detector:
                await completion_detector.stop_timeout_checker()

            # Stop database maintenance
            maintenance = provider.get_service(DatabaseMaintenance)
            if maintenance:
                await maintenance.stop_periodic_cleanup()

            if logger.isEnabledFor(logging.INFO):
                logger.info("ProxyMem services stopped")

        except ImportError:
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Error stopping ProxyMem services: %s", e)

    async def _start_usage_tracking_services(self) -> None:
        """Start usage tracking services (async write queue).

        Starts the AsyncUsageWriteQueue background task for batched
        database writes when database persistence is enabled.
        """
        provider = getattr(self.app.state, "service_provider", None)
        if not provider:
            return

        try:
            from src.core.services.async_usage_write_queue import (
                AsyncUsageWriteQueue,
            )

            write_queue = provider.get_service(AsyncUsageWriteQueue)
            if write_queue:
                await write_queue.start()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Usage write queue started")
        except ImportError:
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Error starting usage write queue: %s", e)

    async def _stop_usage_tracking_services(self) -> None:
        """Stop usage tracking services and drain pending records.

        Gracefully stops the AsyncUsageWriteQueue, ensuring all pending
        usage records are flushed to the database before shutdown.
        """
        provider = getattr(self.app.state, "service_provider", None)
        if not provider:
            return

        try:
            from src.core.services.async_usage_write_queue import (
                AsyncUsageWriteQueue,
            )

            write_queue = provider.get_service(AsyncUsageWriteQueue)
            if write_queue:
                await write_queue.stop()
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Usage write queue stopped and drained")
        except ImportError:
            pass
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning("Error stopping usage write queue: %s", e)

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
