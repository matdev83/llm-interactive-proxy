"""
Shared idempotent registration utilities for DI registrars.

This module provides utilities to reduce duplication and enforce "first registration wins"
semantics across all feature-scoped registrars.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider, ServiceLifetime

logger = logging.getLogger(__name__)


def register_if_absent(
    services: ServiceCollection,
    service_type: type,
    lifetime: ServiceLifetime,
    implementation_type: type | None = None,
    implementation_factory: Callable[[IServiceProvider], Any] | None = None,
    instance: Any | None = None,
) -> bool:
    """Register service only if not already registered.

    Implements "first registration wins" semantics: if a service_type is already
    registered, this function skips registration and returns False.

    Args:
        services: The service collection to register into
        service_type: The service type to register
        lifetime: The service lifetime (SINGLETON, SCOPED, or TRANSIENT)
        implementation_type: Optional implementation type (if different from service_type)
        implementation_factory: Optional factory function to create the service
        instance: Optional existing instance (for singleton services)

    Returns:
        True if registration occurred, False if service was already registered
    """
    # Check if service is already registered
    if service_type in services._descriptors:
        if logger.isEnabledFor(logging.DEBUG):
            type_name = getattr(service_type, "__name__", str(service_type))
            logger.debug(
                "Skipping registration of %s: already registered (first registration wins)",
                type_name,
            )
        return False

    # Register based on lifetime
    if lifetime == ServiceLifetime.SINGLETON:
        if instance is not None:
            services.add_instance(service_type, instance)
        elif implementation_factory is not None:
            services.add_singleton(
                service_type,
                implementation_type=implementation_type,
                implementation_factory=implementation_factory,
            )
        else:
            services.add_singleton(
                service_type, implementation_type=implementation_type
            )
    elif lifetime == ServiceLifetime.SCOPED:
        services.add_scoped(
            service_type,
            implementation_type=implementation_type,
            implementation_factory=implementation_factory,
        )
    elif lifetime == ServiceLifetime.TRANSIENT:
        services.add_transient(
            service_type,
            implementation_type=implementation_type,
            implementation_factory=implementation_factory,
        )
    else:
        raise ValueError(f"Unknown lifetime: {lifetime}")

    return True


def register_singleton_if_absent(
    services: ServiceCollection,
    service_type: type,
    implementation_type: type | None = None,
    implementation_factory: Callable[[IServiceProvider], Any] | None = None,
    instance: Any | None = None,
) -> bool:
    """Register a singleton service only if not already registered.

    Convenience wrapper for register_if_absent with SINGLETON lifetime.

    Args:
        services: The service collection to register into
        service_type: The service type to register
        implementation_type: Optional implementation type (if different from service_type)
        implementation_factory: Optional factory function to create the service
        instance: Optional existing instance (for singleton services)

    Returns:
        True if registration occurred, False if service was already registered
    """
    return register_if_absent(
        services,
        service_type,
        ServiceLifetime.SINGLETON,
        implementation_type=implementation_type,
        implementation_factory=implementation_factory,
        instance=instance,
    )


def register_scoped_if_absent(
    services: ServiceCollection,
    service_type: type,
    implementation_type: type | None = None,
    implementation_factory: Callable[[IServiceProvider], Any] | None = None,
) -> bool:
    """Register a scoped service only if not already registered.

    Convenience wrapper for register_if_absent with SCOPED lifetime.

    Args:
        services: The service collection to register into
        service_type: The service type to register
        implementation_type: Optional implementation type (if different from service_type)
        implementation_factory: Optional factory function to create the service

    Returns:
        True if registration occurred, False if service was already registered
    """
    return register_if_absent(
        services,
        service_type,
        ServiceLifetime.SCOPED,
        implementation_type=implementation_type,
        implementation_factory=implementation_factory,
    )


def register_transient_if_absent(
    services: ServiceCollection,
    service_type: type,
    implementation_type: type | None = None,
    implementation_factory: Callable[[IServiceProvider], Any] | None = None,
) -> bool:
    """Register a transient service only if not already registered.

    Convenience wrapper for register_if_absent with TRANSIENT lifetime.

    Args:
        services: The service collection to register into
        service_type: The service type to register
        implementation_type: Optional implementation type (if different from service_type)
        implementation_factory: Optional factory function to create the service

    Returns:
        True if registration occurred, False if service was already registered
    """
    return register_if_absent(
        services,
        service_type,
        ServiceLifetime.TRANSIENT,
        implementation_type=implementation_type,
        implementation_factory=implementation_factory,
    )


def register_interface_and_implementation(
    services: ServiceCollection,
    interface_type: type,
    implementation_type: type,
    lifetime: ServiceLifetime = ServiceLifetime.SINGLETON,
) -> bool:
    """Register both interface and implementation, binding interface to implementation.

    This is a common pattern where we register both the concrete type and bind
    the interface to it. Uses idempotent registration.

    Args:
        services: The service collection to register into
        interface_type: The interface type to register
        implementation_type: The concrete implementation type
        lifetime: The service lifetime (defaults to SINGLETON)

    Returns:
        True if at least one registration occurred, False if both were already registered
    """
    registered_impl = register_if_absent(
        services,
        implementation_type,
        lifetime,
        implementation_type=implementation_type,
    )

    def _interface_factory(provider: IServiceProvider) -> Any:
        return provider.get_required_service(implementation_type)

    registered_interface = register_if_absent(
        services,
        interface_type,
        lifetime,
        implementation_type=implementation_type,
        implementation_factory=_interface_factory,
    )
    return registered_impl or registered_interface
