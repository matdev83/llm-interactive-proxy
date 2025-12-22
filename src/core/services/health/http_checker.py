"""HTTP health checker for backend API endpoints.

This module provides an async HTTP health checker that probes API endpoints
to verify HTTP connectivity. It uses httpx for async HTTP requests.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import httpx

from src.core.domain.events.health_events import HttpCheckFailed, HttpCheckSucceeded
from src.core.interfaces.event_bus_interface import IEventBus
from src.core.services.health.endpoint_registry import EndpointRegistry

if TYPE_CHECKING:
    from src.core.domain.configuration.health_check_config import HttpCheckConfig

logger = logging.getLogger(__name__)


class HTTPHealthChecker:
    """HTTP health checker for backend API endpoints.

    This checker performs HTTP requests to verify that API endpoints
    are reachable and responding. It supports:
    - GET or HEAD methods
    - Configurable timeouts
    - Accept any HTTP response as success (even 4xx/5xx)
    - Optional custom paths for health check endpoints

    The checker is designed to be non-intrusive - it uses HEAD by default
    and considers any valid HTTP response as a sign that the endpoint is up.
    """

    def __init__(
        self,
        event_bus: IEventBus,
        endpoint_registry: EndpointRegistry,
        config: HttpCheckConfig,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """Initialize the HTTP health checker.

        Args:
            event_bus: Event bus for publishing check results.
            endpoint_registry: Registry of API endpoints to check.
            config: HTTP check configuration.
            http_client: Optional shared HTTP client. If not provided,
                         a dedicated client will be created.
        """
        self._event_bus = event_bus
        self._registry = endpoint_registry
        self._config = config
        self._enabled = config.enabled
        self._owns_client = http_client is None
        self._client = http_client

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client.

        Note: If a client is created here and shutdown() is never called,
        the client will be cleaned up by Python's garbage collector, but
        it's better to ensure shutdown() is always called during app lifecycle.
        """
        if self._client is None:
            # Create a dedicated client for health checks
            # Mark that we own this client for proper cleanup
            self._owns_client = True
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=5.0,
                    read=float(self._config.timeout_seconds),
                    write=5.0,
                    pool=5.0,
                ),
                follow_redirects=True,
                # Don't verify SSL for health checks (we just want to know if it's up)
                verify=True,
            )
        return self._client

    async def check_endpoint(self, api_url: str) -> None:
        """Perform an HTTP health check on an endpoint.

        Args:
            api_url: The API URL to check.
        """
        if not self._enabled:
            return

        # Build the probe URL
        probe_url = self._build_probe_url(api_url)

        start_time = time.perf_counter()
        try:
            client = await self._get_client()

            # Use configured method
            if self._config.method.upper() == "HEAD":
                response = await client.head(
                    probe_url,
                    timeout=self._config.timeout_seconds,
                )
            else:
                response = await client.get(
                    probe_url,
                    timeout=self._config.timeout_seconds,
                )

            latency_ms = (time.perf_counter() - start_time) * 1000

            # Check if we should accept any response or only success codes
            if self._config.accept_any_response:
                # Any valid HTTP response is considered success
                success_event = HttpCheckSucceeded(
                    api_url=api_url,
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                )
                await self._event_bus.publish(success_event)
            elif response.is_success:
                success_event = HttpCheckSucceeded(
                    api_url=api_url,
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                )
                await self._event_bus.publish(success_event)
            else:
                failure_event = HttpCheckFailed(
                    api_url=api_url,
                    error=f"HTTP {response.status_code}",
                )
                await self._event_bus.publish(failure_event)

        except httpx.TimeoutException as e:
            failure_event = HttpCheckFailed(
                api_url=api_url,
                error=f"Timeout: {type(e).__name__}",
            )
            await self._event_bus.publish(failure_event)
            logger.debug("HTTP check timeout for %s: %s", api_url, e)

        except httpx.ConnectError as e:
            failure_event = HttpCheckFailed(
                api_url=api_url,
                error=f"Connection error: {e}",
            )
            await self._event_bus.publish(failure_event)
            logger.debug("HTTP connection error for %s: %s", api_url, e)

        except httpx.HTTPError as e:
            failure_event = HttpCheckFailed(
                api_url=api_url,
                error=f"HTTP error: {type(e).__name__}: {e}",
            )
            await self._event_bus.publish(failure_event)
            logger.debug("HTTP check failed for %s: %s", api_url, e)

        except Exception as e:
            failure_event = HttpCheckFailed(
                api_url=api_url,
                error=f"Unexpected error: {type(e).__name__}: {e}",
            )
            await self._event_bus.publish(failure_event)
            logger.debug("HTTP check unexpected error for %s: %s", api_url, e)

    def _build_probe_url(self, api_url: str) -> str:
        """Build the full URL for health check probing.

        Args:
            api_url: The base API URL.

        Returns:
            The full probe URL with optional path appended.
        """
        # Normalize URL - remove trailing slash
        base_url = api_url.rstrip("/")

        # Append configured path if any
        if self._config.path:
            path = self._config.path.lstrip("/")
            return f"{base_url}/{path}"

        return base_url

    async def check_all_endpoints(self) -> None:
        """Check all registered endpoints.

        This runs HTTP checks for all unique API URLs in the registry.
        """
        if not self._enabled:
            return

        urls = self._registry.get_all_urls()
        if not urls:
            return

        # Run checks concurrently
        tasks = [self.check_endpoint(url) for url in urls]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        """Shutdown the HTTP checker and clean up resources.

        This method is idempotent and can be called multiple times safely.
        """
        self._enabled = False
        if self._owns_client and self._client is not None:
            try:
                if not self._client.is_closed:
                    await self._client.aclose()
            except Exception as e:
                # Log but don't fail - client might already be closed
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Error closing HTTP client during shutdown: %s", e)
            finally:
                self._client = None
        logger.info("HTTP health checker shutdown complete")


# Native health check endpoints for known backends
BACKEND_HEALTH_ENDPOINTS: dict[str, str] = {
    # OpenAI API doesn't have a dedicated health endpoint
    "api.openai.com": "",
    # Anthropic API
    "api.anthropic.com": "",
    # Google Cloud APIs
    "generativelanguage.googleapis.com": "",
    "cloudcode-pa.googleapis.com": "",
    # OpenRouter
    "openrouter.ai": "/api/v1/models",
    # Minimax
    "api.minimax.io": "",
}


def get_health_path_for_host(hostname: str) -> str | None:
    """Get the native health check path for a known backend.

    Args:
        hostname: The hostname of the API.

    Returns:
        The health check path, or None if no special path is known.
    """
    return BACKEND_HEALTH_ENDPOINTS.get(hostname.lower())
