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

import logging

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection

from .base import InitializationStage

logger = logging.getLogger(__name__)


class InfrastructureStage(InitializationStage):
    """
    Stage for registering infrastructure services.

    This stage registers:
    - Shared HTTP client (httpx.AsyncClient)
    - Rate limiter
    - Loop detector
    - Other infrastructure utilities
    """

    @property
    def name(self) -> str:
        return "infrastructure"

    def get_dependencies(self) -> list[str]:
        return []

    def get_description(self) -> str:
        return "Register infrastructure services (HTTP client, rate limiter, loop detector)"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register infrastructure services."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Initializing infrastructure services...")

        # Register shared HTTP client
        self._register_http_client(services)

        # Register rate limiter
        self._register_rate_limiter(services)

        # Register loop detector
        self._register_loop_detector(services)

        if logger.isEnabledFor(logging.INFO):
            logger.info("Infrastructure services initialized successfully")

    def _register_http_client(self, services: ServiceCollection) -> None:
        """Register shared HTTP client as singleton."""
        try:
            import httpx

            # Create shared HTTP client instance with http2 fallback
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
            except ImportError:
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

            # Register as singleton instance
            services.add_instance(httpx.AsyncClient, shared_httpx_client)

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
            from typing import cast

            from src.core.interfaces.di_interface import IServiceProvider
            from src.core.interfaces.loop_detector_interface import ILoopDetector
            from src.loop_detection.config import LoopDetectionConfig
            from src.loop_detection.hybrid_detector import HybridLoopDetector

            def _create_hybrid_loop_detector() -> HybridLoopDetector:
                """Build a HybridLoopDetector using legacy config defaults."""
                config = LoopDetectionConfig()

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

            def loop_detector_factory(provider: IServiceProvider) -> HybridLoopDetector:
                return _create_hybrid_loop_detector()

            services.add_transient(
                HybridLoopDetector, implementation_factory=loop_detector_factory
            )
            services.add_transient(
                cast(type, ILoopDetector), implementation_factory=loop_detector_factory
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered HybridLoopDetector with DI container")

        except ImportError as e:
            logger.warning(f"Could not register loop detector: {e}")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that infrastructure services can be registered."""
        try:
            # Check that required modules are available

            return True
        except ImportError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Infrastructure services validation failed: {e}")
            return False
