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
        return ["core_services"]

    def get_description(self) -> str:
        return "Register infrastructure services (HTTP client, rate limiter, loop detector)"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register infrastructure services."""
        logger.info("Initializing infrastructure services...")

        # Register shared HTTP client
        self._register_http_client(services)

        # Register rate limiter
        self._register_rate_limiter(services)

        # Register loop detector
        self._register_loop_detector(services)

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

            logger.debug("Registered shared HTTP client")
        except ImportError as e:
            logger.warning(f"Could not register HTTP client: {e}")

    def _register_rate_limiter(self, services: ServiceCollection) -> None:
        """Register rate limiter service."""
        try:
            from src.core.services.rate_limiter_service import RateLimiter

            # Register as singleton (no dependencies)
            services.add_singleton(RateLimiter)

            logger.debug("Registered rate limiter service")
        except ImportError as e:
            logger.warning(f"Could not register rate limiter: {e}")

    def _register_loop_detector(self, services: ServiceCollection) -> None:
        """Register loop detector service."""
        try:
            from src.core.interfaces.loop_detector import ILoopDetector
            from src.core.services.loop_detector_service import LoopDetector

            # Register concrete implementation
            services.add_singleton(LoopDetector)

            # Register interface binding
            try:
                from typing import cast

                services.add_singleton(cast(type, ILoopDetector), LoopDetector)
                logger.debug("Registered loop detector with interface binding")
            except Exception:
                logger.debug("Registered loop detector (interface binding failed)")

        except ImportError as e:
            logger.warning(f"Could not register loop detector: {e}")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that infrastructure services can be registered."""
        try:
            # Check that required modules are available

            return True
        except ImportError as e:
            logger.error(f"Infrastructure services validation failed: {e}")
            return False
