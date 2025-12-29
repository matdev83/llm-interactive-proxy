"""
Backend infrastructure registration helpers.

Handles registration of foundational infrastructure:
- HTTP Client
- Rate Limiter
- Wire Capture
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_http_client(services: ServiceCollection) -> None:
    """Register shared httpx.AsyncClient for backend calls."""
    try:
        import httpx

        def _client_factory(provider: IServiceProvider) -> httpx.AsyncClient:
            try:
                return httpx.AsyncClient(
                    http2=True,
                    timeout=httpx.Timeout(
                        connect=10.0,
                        read=60.0,
                        write=60.0,
                        pool=60.0,
                    ),
                    limits=httpx.Limits(
                        max_connections=100,
                        max_keepalive_connections=20,
                    ),
                    trust_env=False,
                )
            except ImportError as e:
                # Fallback to HTTP/1.1 when optional HTTP/2 deps are missing.
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "HTTP/2 client creation failed, falling back to HTTP/1.1: %s",
                        e,
                    )
                return httpx.AsyncClient(
                    http2=False,
                    timeout=httpx.Timeout(
                        connect=10.0,
                        read=60.0,
                        write=60.0,
                        pool=60.0,
                    ),
                    limits=httpx.Limits(
                        max_connections=100,
                        max_keepalive_connections=20,
                    ),
                    trust_env=False,
                )
            except (ValueError, RuntimeError, OSError, httpx.UnsupportedProtocol) as e:
                # Fallback to HTTP/1.1 if HTTP/2 setup fails
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "HTTP/2 client creation failed, falling back to HTTP/1.1: %s",
                        e,
                        exc_info=True,
                    )
                return httpx.AsyncClient(
                    http2=False,
                    timeout=httpx.Timeout(
                        connect=10.0,
                        read=60.0,
                        write=60.0,
                        pool=60.0,
                    ),
                    limits=httpx.Limits(
                        max_connections=100,
                        max_keepalive_connections=20,
                    ),
                    trust_env=False,
                )

        register_singleton_if_absent(
            services,
            httpx.AsyncClient,
            implementation_factory=_client_factory,
        )
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Could not register httpx.AsyncClient: %s", e)


def register_rate_limiter(services: ServiceCollection) -> None:
    """Register rate limiter service and IRateLimiter interface alias."""
    try:
        from src.core.interfaces.rate_limiter_interface import IRateLimiter
        from src.core.services.rate_limiter import RateLimiter

        register_singleton_if_absent(services, RateLimiter)

        def _rate_limiter_alias_factory(provider: IServiceProvider) -> RateLimiter:
            return provider.get_required_service(RateLimiter)

        register_singleton_if_absent(
            services,
            cast(type, IRateLimiter),
            implementation_factory=_rate_limiter_alias_factory,
        )
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Could not register rate limiter: %s", e)


def register_wire_capture(services: ServiceCollection) -> None:
    """Register a default wire capture service (no-op when disabled by config)."""
    try:
        from src.core.interfaces.wire_capture_interface import IWireCapture
        from src.core.services.wire_capture_service import WireCapture

        def _wire_capture_factory(provider: IServiceProvider) -> WireCapture:
            config = provider.get_required_service(AppConfig)
            return WireCapture(config)

        register_singleton_if_absent(
            services,
            WireCapture,
            implementation_factory=_wire_capture_factory,
        )

        def _wire_capture_alias_factory(provider: IServiceProvider) -> WireCapture:
            return provider.get_required_service(WireCapture)

        register_singleton_if_absent(
            services,
            cast(type, IWireCapture),
            implementation_factory=_wire_capture_alias_factory,
        )
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Could not register wire capture service: %s", e)
