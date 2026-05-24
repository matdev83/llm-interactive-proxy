"""Health check scheduler for running periodic background checks.

This module provides the scheduler that runs health checks at configured
intervals in background asyncio tasks.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.domain.configuration.health_check_config import HealthCheckConfig
    from src.core.services.health.http_checker import HTTPHealthChecker
    from src.core.services.health.icmp_checker import ICMPHealthChecker

logger = logging.getLogger(__name__)


class HealthCheckScheduler:
    """Schedules and runs periodic health checks in background tasks.

    This scheduler manages two independent check loops:
    - ICMP ping checks (if enabled)
    - HTTP checks (if enabled)

    Each loop runs at its configured interval and is completely independent.
    Errors in one check don't affect the other or the main application.
    """

    def __init__(
        self,
        icmp_checker: ICMPHealthChecker,
        http_checker: HTTPHealthChecker,
        config: HealthCheckConfig,
    ) -> None:
        """Initialize the health check scheduler.

        Args:
            icmp_checker: ICMP ping health checker.
            http_checker: HTTP health checker.
            config: Health check configuration.
        """
        self._icmp_checker = icmp_checker
        self._http_checker = http_checker
        self._config = config
        self._ping_task: asyncio.Task[None] | None = None
        self._http_task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        """Return True if the scheduler is running."""
        return self._running

    async def start(self) -> None:
        """Start the background health check loops.

        This method creates asyncio tasks for each enabled check type.
        """
        if self._running:
            logger.warning("Health check scheduler already running")
            return

        if not self._config.enabled:
            logger.info("Health checks disabled by configuration")
            return

        self._running = True

        # Start ping check loop if enabled
        if self._config.ping.enabled:
            self._ping_task = asyncio.create_task(
                self._ping_check_loop(),
                name="health_check_ping",
            )
            logger.info(
                "Started ping health check loop (interval: %ds)",
                self._config.ping.interval_seconds,
            )

        # Start HTTP check loop if enabled
        if self._config.http.enabled:
            self._http_task = asyncio.create_task(
                self._http_check_loop(),
                name="health_check_http",
            )
            logger.info(
                "Started HTTP health check loop (interval: %ds)",
                self._config.http.interval_seconds,
            )

        logger.info("Health check scheduler started")

    async def stop(self) -> None:
        """Stop the background health check loops.

        This method cancels the check tasks and waits for them to complete.
        """
        if not self._running:
            return

        self._running = False

        import contextlib

        # Cancel ping task
        if self._ping_task is not None and not self._ping_task.done():
            self._ping_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._ping_task, timeout=5.0)
            self._ping_task = None

        # Cancel HTTP task
        if self._http_task is not None and not self._http_task.done():
            self._http_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(self._http_task, timeout=5.0)
            self._http_task = None

        logger.info("Health check scheduler stopped")

    async def _ping_check_loop(self) -> None:
        """Background loop for periodic ping checks."""
        interval = self._config.ping.interval_seconds

        # Initial delay to let the system stabilize
        await asyncio.sleep(5.0)

        while self._running:
            try:
                await self._icmp_checker.check_all_endpoints()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in ping check loop: %s", e)

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def _http_check_loop(self) -> None:
        """Background loop for periodic HTTP checks."""
        interval = self._config.http.interval_seconds

        # Initial delay to let the system stabilize
        await asyncio.sleep(10.0)

        while self._running:
            try:
                await self._http_checker.check_all_endpoints()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error in HTTP check loop: %s", e)

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def run_immediate_checks(self) -> None:
        """Run health checks immediately without waiting for the next interval.

        This is useful for on-demand health status updates.
        """
        if not self._config.enabled:
            return

        tasks = []

        if self._config.ping.enabled:
            tasks.append(self._icmp_checker.check_all_endpoints())

        if self._config.http.enabled:
            tasks.append(self._http_checker.check_all_endpoints())

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        """Shutdown the scheduler and all checkers."""
        await self.stop()
        await self._icmp_checker.shutdown()
        await self._http_checker.shutdown()
        logger.info("Health check scheduler shutdown complete")
