"""ICMP ping health checker using ping3 library.

This module provides an async-compatible ICMP ping checker that runs
in a thread pool to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from src.core.domain.events.health_events import PingCheckFailed, PingCheckSucceeded
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.services.health.endpoint_registry import EndpointRegistry

if TYPE_CHECKING:
    from src.core.domain.configuration.health_check_config import PingCheckConfig

logger = logging.getLogger(__name__)

# Thread pool for running blocking ping operations
_ping_executor: ThreadPoolExecutor | None = None


def _get_ping_executor() -> ThreadPoolExecutor:
    """Get or create the shared thread pool for ping operations."""
    global _ping_executor
    if _ping_executor is None:
        # Use a small pool since pings are quick but may need parallelism
        _ping_executor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="ping_check"
        )
    return _ping_executor


def _shutdown_ping_executor() -> None:
    """Shutdown the ping thread pool."""
    global _ping_executor
    if _ping_executor is not None:
        _ping_executor.shutdown(wait=False)
        _ping_executor = None


class ICMPHealthChecker:
    """ICMP ping health checker for backend API endpoints.

    This checker performs ICMP ping checks on hostnames extracted from API URLs.
    It runs in a thread pool to avoid blocking the async event loop.

    Note: ICMP ping may require elevated privileges on some systems.
    If ping3 fails due to permissions, errors are logged but the system
    continues to operate using HTTP checks alone.
    """

    def __init__(
        self,
        event_bus: IEventBus,
        endpoint_registry: EndpointRegistry,
        config: PingCheckConfig,
    ) -> None:
        """Initialize the ICMP health checker.

        Args:
            event_bus: Event bus for publishing check results.
            endpoint_registry: Registry of API endpoints to check.
            config: Ping check configuration.
        """
        self._event_bus = event_bus
        self._registry = endpoint_registry
        self._config = config
        self._enabled = config.enabled
        self._ping_available: bool | None = None  # None = not tested yet

    @property
    def enabled(self) -> bool:
        """Return True if ping checks are enabled and available."""
        return self._enabled and self._ping_available is not False

    async def check_endpoint(self, api_url: str) -> None:
        """Perform a ping check on an endpoint.

        Args:
            api_url: The API URL to check (hostname will be extracted).
        """
        if not self._enabled:
            return

        hostname = EndpointRegistry.extract_hostname(api_url)
        if not hostname:
            logger.warning("Cannot extract hostname from URL: %s", api_url)
            return

        try:
            latency_ms = await self._do_ping(
                hostname,
                timeout=self._config.timeout_seconds,
                count=self._config.count,
            )

            if latency_ms is not None:
                # Ping succeeded
                success_event = PingCheckSucceeded(
                    api_url=api_url,
                    latency_ms=latency_ms,
                )
                await self._event_bus.publish(success_event)
            else:
                # Ping failed (no response)
                failure_event = PingCheckFailed(
                    api_url=api_url,
                    error="No response (timeout)",
                )
                await self._event_bus.publish(failure_event)

        except PermissionError as e:
            # ping3 requires elevated privileges on some systems
            self._ping_available = False
            logger.warning(
                "ICMP ping requires elevated privileges. Disabling ping checks. Error: %s",
                e,
            )
            # Don't emit event - just disable ping checks
        except Exception as e:
            failure_event = PingCheckFailed(
                api_url=api_url,
                error=str(e),
            )
            await self._event_bus.publish(failure_event)
            logger.debug("Ping check failed for %s: %s", hostname, e)

    async def _do_ping(
        self,
        hostname: str,
        timeout: int,
        count: int,
    ) -> float | None:
        """Perform the actual ping in a thread pool.

        Args:
            hostname: The hostname to ping.
            timeout: Timeout in seconds.
            count: Number of ping packets.

        Returns:
            Average latency in milliseconds, or None if ping failed.
        """
        loop = asyncio.get_event_loop()
        executor = _get_ping_executor()

        try:
            result = await loop.run_in_executor(
                executor,
                self._blocking_ping,
                hostname,
                timeout,
                count,
            )
            return result
        except Exception as e:
            logger.debug("Ping executor error for %s: %s", hostname, e)
            raise

    def _blocking_ping(
        self,
        hostname: str,
        timeout: int,
        count: int,
    ) -> float | None:
        """Blocking ping implementation using ping3.

        Args:
            hostname: The hostname to ping.
            timeout: Timeout in seconds.
            count: Number of ping packets.

        Returns:
            Average latency in milliseconds, or None if ping failed.
        """
        try:
            import ping3
        except ImportError:
            logger.warning("ping3 library not installed. Disabling ping checks.")
            self._ping_available = False
            return None

        if self._ping_available is None:
            self._ping_available = True  # Assume available until proven otherwise

        latencies: list[float] = []
        start_time = time.perf_counter()

        for _ in range(count):
            try:
                # ping3.ping returns delay in seconds, or None/False on failure
                delay = ping3.ping(hostname, timeout=timeout)

                if delay is not None and delay is not False:
                    # Convert to milliseconds
                    latencies.append(delay * 1000)
                else:
                    # Single ping failed, but keep trying
                    pass

            except PermissionError:
                # Re-raise to be handled in check_endpoint
                raise
            except Exception as e:
                logger.debug("Single ping failed for %s: %s", hostname, e)

            # Check if we've exceeded total timeout
            elapsed = time.perf_counter() - start_time
            if elapsed > timeout * count:
                break

        if latencies:
            return sum(latencies) / len(latencies)
        return None

    async def check_all_endpoints(self) -> None:
        """Check all registered endpoints.

        This runs ping checks for all unique API URLs in the registry.
        """
        if not self._enabled or self._ping_available is False:
            return

        urls = self._registry.get_all_urls()
        if not urls:
            return

        # Run checks concurrently with some throttling
        tasks = [self.check_endpoint(url) for url in urls]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        """Shutdown the ping checker and clean up resources."""
        self._enabled = False
        _shutdown_ping_executor()
        logger.info("ICMP health checker shutdown complete")
