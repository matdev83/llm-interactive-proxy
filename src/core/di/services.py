"""
Services and DI container configuration.

This module provides functions for configuring DI container with services
and resolving services from container.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, TypeVar

from src.core.common.exceptions import ServiceResolutionError
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.di_interface import IServiceProvider

# Note: IMiddlewareApplicationManager interface is no longer used after unified pipeline refactoring
# MiddlewareApplicationManager is still used to configure middleware list for streaming processors

T = TypeVar("T")

# Global service collection
_service_collection: ServiceCollection | None = None
_service_collection_lock = threading.Lock()

# Global service provider (legacy compatibility shim).
#
# The canonical provider state lives in src.core.di.provider_lifecycle, but some
# tests and legacy call sites still reset/inspect this module-level variable.
# provider_lifecycle keeps this value in sync.
_service_provider: IServiceProvider | None = None


def _get_di_diagnostics() -> bool:
    """Get DI diagnostics setting from environment."""
    return os.getenv("DI_STRICT_DIAGNOSTICS", "false").lower() in (
        "true",
        "1",
        "yes",
    )


def get_service_collection() -> ServiceCollection:
    """Get the global service collection.

    Returns:
        The global service collection
    """
    global _service_collection
    if _service_collection is not None:
        return _service_collection

    with _service_collection_lock:
        if _service_collection is None:
            _service_collection = ServiceCollection()
            # Ensure core services are registered into the global collection early.
            # This makes DI shape consistent across processes/tests and avoids many
            # order-dependent failures. register_core_services is idempotent.
            try:
                register_core_services(_service_collection, None)
            except Exception as exc:
                logger_for_this_file = logging.getLogger(__name__)
                if logger_for_this_file.isEnabledFor(logging.ERROR):
                    logger_for_this_file.error(
                        "Failed to register core services into global service collection",
                        exc_info=True,
                    )
                _service_collection = None
                raise ServiceResolutionError(
                    "Failed to register core services",
                    details={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                ) from exc

    return _service_collection


def get_or_build_service_provider() -> IServiceProvider:
    """Get the global service provider or build one if it doesn't exist.

    Returns:
        The global service provider
    """
    from src.core.di import provider_lifecycle

    return provider_lifecycle.get_or_build_service_provider()


def set_service_provider(provider: IServiceProvider | None) -> None:
    """Set the global service provider (used for tests/late init).

    Args:
        provider: The ServiceProvider instance to set as the global provider, or None to reset
    """
    from src.core.di import provider_lifecycle

    provider_lifecycle.set_service_provider(provider)


def get_service_provider() -> IServiceProvider:
    """Return the global service provider, building it if necessary.

    This is a compatibility wrapper used by callers that expect a
    `get_service_provider` symbol. Returns the provider as-is without
    any self-healing behavior.
    """
    from src.core.di import provider_lifecycle

    return provider_lifecycle.get_service_provider()


def _resolve_failure_strategy(
    provider: IServiceProvider,
    config: IConfig,
    routing_service: Any = None,
) -> Any:
    """Resolve failure handling strategy from DI or construct from config.

    DEPRECATED: Use src.core.di.registration_helpers.failure_handling.resolve_failure_strategy
    instead. This function is kept for backward compatibility but delegates to the stable helper.

    Args:
        provider: DI service provider
        config: Application configuration
        routing_service: Optional routing service for backend discovery

    Returns:
        IFailureHandlingStrategy instance or None if disabled
    """
    from src.core.di.registration_helpers.failure_handling import (
        resolve_failure_strategy,
    )

    return resolve_failure_strategy(provider, config, routing_service)


def register_core_services(
    services: ServiceCollection, app_config: AppConfig | None = None
) -> None:
    """Register core services with service collection.

    This function is a public compatibility facade for DI wiring.

    It delegates to the registrar orchestrator so legacy call sites get a
    complete, deterministic registration set aligned with the approved design.

    Args:
        services: The service collection to register services with
        app_config: Optional application configuration
    """
    from src.core.di.registrations._orchestrator import register_all

    register_all(services, app_config)


def get_service(service_type: type[T]) -> T | None:
    """Get a service from the global service provider.

    Args:
        service_type: The type of service to get

    Returns:
        The service instance, or None if service is not registered
    """
    provider = get_or_build_service_provider()
    return provider.get_service(service_type)  # type: ignore


def get_required_service(service_type: type[T]) -> T:
    """Get a required service from the global service provider.

    Args:
        service_type: The type of service to get

    Returns:
        The service instance

    Raises:
        Exception: If the service is not registered
    """
    provider = get_or_build_service_provider()
    return provider.get_required_service(service_type)  # type: ignore
