"""
Infrastructure services initialization stage.

This stage registers infrastructure services that provide foundational
capabilities but don't contain business logic:
- HTTP client
- Rate limiter
- Loop detector
- Caching services
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection

from .base import InitializationStage

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import httpx


class InfrastructureStage(InitializationStage):
    """
    Stage for registering infrastructure services.

    This stage registers:
    - Shared HTTP client (httpx.AsyncClient)
    - Rate limiter
    - Loop detector
    - Other infrastructure utilities
    """

    def __init__(self) -> None:
        super().__init__()
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._http_client: httpx.AsyncClient | None = None

    def __del__(self) -> None:
        """Defensive cleanup of HTTP client.

        This ensures httpx.AsyncClient is closed even if:
        - The stage is destroyed before proper shutdown
        - An exception prevents execute() from completing
        - The application crashes

        This is a last-resort cleanup and should not be relied upon
        for normal resource management (use shutdown/cleanup methods).
        """
        if self._http_client is not None and hasattr(self._http_client, "is_closed"):
            try:
                if not self._http_client.is_closed:
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            task = loop.create_task(self._http_client.aclose())
                            self._cleanup_tasks.add(task)
                        else:
                            loop.run_until_complete(self._http_client.aclose())
                    except (RuntimeError, AttributeError):
                        pass
            except Exception:
                pass

    @property
    def name(self) -> str:
        return "infrastructure"

    def get_dependencies(self) -> list[str]:
        return []

    def get_description(self) -> str:
        return "Register infrastructure services (HTTP client, rate limiter, loop detector)"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register infrastructure services."""
        try:
            if logger.isEnabledFor(logging.INFO):
                logger.info("Initializing infrastructure services...")

            # Register shared HTTP client
            self._register_http_client(services)

            # Register rate limiter
            self._register_rate_limiter(services)

            # Register loop detector
            self._register_loop_detector(services)

            # Configure streaming sampler
            self._configure_streaming_sampler(config)

            if logger.isEnabledFor(logging.INFO):
                logger.info("Infrastructure services initialized successfully")
        except BaseException as err:
            await self._cleanup_http_client()
            raise err

    def _configure_streaming_sampler(self, config: AppConfig) -> None:
        """Configure the streaming sampler with settings from AppConfig."""
        try:
            from src.core.ports.streaming_metrics import configure_sampler

            sampler_config = config.session.streaming_sampler
            configure_sampler(
                sample_rate=sampler_config.sample_rate,
                max_samples=sampler_config.max_samples,
                enabled=sampler_config.enabled,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Configured streaming sampler: enabled=%s, rate=%s, max=%s",
                    sampler_config.enabled,
                    sampler_config.sample_rate,
                    sampler_config.max_samples,
                )
        except (ImportError, AttributeError, KeyError) as err:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Could not configure streaming sampler: %s",
                    err,
                    exc_info=True,
                )

    def _register_http_client(self, services: ServiceCollection) -> None:
        """Register shared HTTP client as singleton."""
        try:
            import httpx

            provider = services.build_service_provider()
            if provider.get_service(httpx.AsyncClient) is not None:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Shared HTTP client already registered; skipping registration"
                    )
                return

            # Create shared HTTP client instance with http2 fallback
            shared_httpx_client: httpx.AsyncClient | None = None
            try:
                shared_httpx_client = httpx.AsyncClient(
                    http2=True,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )
            except (ValueError, RuntimeError, OSError, httpx.UnsupportedProtocol):
                # Fallback to HTTP/1.1 if HTTP/2 setup fails
                shared_httpx_client = httpx.AsyncClient(
                    http2=False,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )

            if shared_httpx_client is None:
                raise RuntimeError("Failed to create shared HTTP client")

            self._http_client = shared_httpx_client

            # Register as singleton instance
            try:
                services.add_instance(httpx.AsyncClient, shared_httpx_client)
            except (TypeError, ValueError, RuntimeError) as err:
                # Registration failed - clean up and rethrow
                self._schedule_http_client_cleanup(shared_httpx_client)
                self._http_client = None
                raise err

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered shared HTTP client")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register HTTP client: {e}")

    def _register_rate_limiter(self, services: ServiceCollection) -> None:
        """Register rate limiter service."""
        try:
            from src.core.services.rate_limiter import RateLimiter

            # Register as singleton (no dependencies)
            services.add_singleton(RateLimiter)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered rate limiter service")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register rate limiter: {e}")

    def _register_loop_detector(self, services: ServiceCollection) -> None:
        """Register loop detector service."""
        try:
            import os
            from typing import cast

            from src.core.interfaces.di_interface import IServiceProvider
            from src.core.interfaces.loop_detector_interface import ILoopDetector
            from src.loop_detection.config import InternalLoopDetectionConfig
            from src.loop_detection.hybrid_detector import HybridLoopDetector

            # Check if loop detection is enabled in config (read from environment)
            config = InternalLoopDetectionConfig.from_env_vars(dict(os.environ))

            if config.enabled:

                def _create_hybrid_loop_detector() -> HybridLoopDetector:
                    """Build a HybridLoopDetector using legacy config defaults."""
                    short_config = {
                        "content_loop_threshold": config.content_loop_threshold,
                        "content_chunk_size": config.content_chunk_size,
                        "max_history_length": config.max_history_length,
                    }

                    long_threshold = config.long_pattern_threshold
                    if long_threshold is None:
                        raise ValueError(
                            "LoopDetectionConfig.long_pattern_threshold must be set"
                        )

                    min_repetitions = max(long_threshold.min_repetitions, 1)
                    min_pattern_length = max(
                        long_threshold.min_total_length // min_repetitions,
                        60,
                    )

                    long_config = {
                        "min_pattern_length": min(
                            min_pattern_length, config.max_pattern_length
                        ),
                        "max_pattern_length": config.max_pattern_length,
                        "min_repetitions": long_threshold.min_repetitions,
                        "max_history": config.max_history_length,
                    }

                    return HybridLoopDetector(
                        short_detector_config=short_config,
                        long_detector_config=long_config,
                    )

                def loop_detector_factory(
                    provider: IServiceProvider,
                ) -> HybridLoopDetector:
                    return _create_hybrid_loop_detector()

                services.add_transient(
                    HybridLoopDetector, implementation_factory=loop_detector_factory
                )
                services.add_transient(
                    cast(type, ILoopDetector),
                    implementation_factory=loop_detector_factory,
                )

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Registered HybridLoopDetector with DI container")
            else:
                # Register no-op detector when loop detection is disabled
                from src.loop_detection.detector import NoOpLoopDetector

                def noop_detector_factory(
                    provider: IServiceProvider,
                ) -> NoOpLoopDetector:
                    return NoOpLoopDetector()

                services.add_transient(
                    cast(type, ILoopDetector),
                    implementation_factory=noop_detector_factory,
                )

                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Loop detection disabled, registered NoOpLoopDetector")

        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register loop detector: {e}")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that infrastructure services can be registered."""
        try:
            # Check that required modules are available

            return True
        except ImportError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Infrastructure services validation failed: %s", e, exc_info=True
                )
            return False

    async def _cleanup_http_client(self) -> None:
        if self._http_client is not None:
            client = self._http_client
            self._http_client = None
            self._schedule_http_client_cleanup(client)

        pending_tasks = [t for t in self._cleanup_tasks if not t.done()]
        if pending_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending_tasks, return_exceptions=True),
                    timeout=5.0,
                )
            except asyncio.TimeoutError:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Timeout waiting for HTTP client cleanup tasks")
                for task in pending_tasks:
                    if not task.done():
                        task.cancel()
                with contextlib.suppress(Exception):
                    await asyncio.gather(*pending_tasks, return_exceptions=True)
            except Exception as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Cleanup task gather failed: %s", e)
                for task in pending_tasks:
                    if not task.done():
                        task.cancel()
                with contextlib.suppress(Exception):
                    await asyncio.gather(*pending_tasks, return_exceptions=True)

        self._cleanup_tasks.clear()

    def _schedule_http_client_cleanup(self, client: httpx.AsyncClient) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is None or not loop.is_running():
            try:
                asyncio.run(client.aclose())
            except RuntimeError:
                try:
                    loop = asyncio.get_event_loop()
                    loop.run_until_complete(client.aclose())
                except (RuntimeError, OSError, asyncio.CancelledError) as err:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Failed to close HTTP client during cleanup: %s",
                            err,
                            exc_info=True,
                        )
            return

        cleanup_task = loop.create_task(client.aclose())
        self._cleanup_tasks.add(cleanup_task)
        cleanup_task.add_done_callback(self._cleanup_tasks.discard)
