"""
Services and DI container configuration.

This module provides functions for configuring DI container with services
and resolving services from container.
"""

from __future__ import annotations

import threading
from typing import TypeVar

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
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
            # Keep the global collection empty by default.
            #
            # Callers that build a global provider directly should explicitly invoke
            # register_core_services() before building (provider_lifecycle does this).
            # This avoids front-loading full registration during app startup where
            # staged initialization will perform registrations with runtime config.
            _service_collection = ServiceCollection()

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
