"""
Non-forwardable message tagging registrar.

Registers identity computation, tag registry, and enforcement services.
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import (
    register_interface_and_implementation,
    register_singleton_if_absent,
)
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register(services: ServiceCollection, app_config: AppConfig | None) -> None:
    """Register non-forwardable message tagging services.

    This registrar handles:
    - NonForwardableMessageIdentityService: deterministic message identity computation
    - NonForwardableMessageRegistry: session-scoped tag storage and lookup
    - NonForwardableMessageEnforcer: message filtering before backend calls

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    # Register identity service (stateless singleton)
    _register_identity_service(services)

    # Register registry service (singleton with config dependency)
    _register_registry_service(services, app_config)

    # Register enforcer service (singleton with dependencies)
    _register_enforcer_service(services)


def _register_identity_service(services: ServiceCollection) -> None:
    """Register identity computation service and interface."""
    try:
        from src.core.interfaces.non_forwardable_interface import (
            INonForwardableMessageIdentityService,
        )
        from src.core.services.non_forwardable_message_identity_service import (
            NonForwardableMessageIdentityService,
        )

        # Register as singleton (stateless service)
        register_singleton_if_absent(services, NonForwardableMessageIdentityService)

        # Register interface binding
        register_interface_and_implementation(
            services,
            cast(type, INonForwardableMessageIdentityService),
            NonForwardableMessageIdentityService,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered NonForwardableMessageIdentityService")
    except ImportError as e:
        logger.warning(
            "Could not register non-forwardable identity service: %s", e, exc_info=True
        )


def _register_registry_service(
    services: ServiceCollection, app_config: AppConfig | None
) -> None:
    """Register tag registry service and interface."""
    try:
        from src.core.interfaces.non_forwardable_interface import (
            INonForwardableMessageRegistry,
        )
        from src.core.services.non_forwardable_message_registry import (
            NonForwardableMessageRegistry,
        )

        def registry_factory(
            provider: IServiceProvider,
        ) -> NonForwardableMessageRegistry:
            """Factory function for creating registry with config dependency."""
            # Get AppConfig from provider
            config: AppConfig = provider.get_required_service(AppConfig)
            return NonForwardableMessageRegistry(config)

        # Register as singleton with factory
        register_singleton_if_absent(
            services,
            NonForwardableMessageRegistry,
            implementation_factory=registry_factory,
        )

        # Register interface binding
        register_interface_and_implementation(
            services,
            cast(type, INonForwardableMessageRegistry),
            NonForwardableMessageRegistry,
            implementation_factory=registry_factory,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered NonForwardableMessageRegistry")
    except ImportError as e:
        logger.warning(
            "Could not register non-forwardable registry service: %s", e, exc_info=True
        )


def _register_enforcer_service(services: ServiceCollection) -> None:
    """Register enforcer service and interface."""
    try:
        from src.core.interfaces.non_forwardable_interface import (
            INonForwardableMessageEnforcer,
            INonForwardableMessageIdentityService,
            INonForwardableMessageRegistry,
        )
        from src.core.services.non_forwardable_message_enforcer import (
            NonForwardableMessageEnforcer,
        )

        def enforcer_factory(
            provider: IServiceProvider,
        ) -> NonForwardableMessageEnforcer:
            """Factory function for creating enforcer with dependencies."""
            # Get dependencies from provider
            from typing import cast

            identity_service: INonForwardableMessageIdentityService = (
                provider.get_required_service(
                    cast(type, INonForwardableMessageIdentityService)
                )
            )
            registry: INonForwardableMessageRegistry = provider.get_required_service(
                cast(type, INonForwardableMessageRegistry)
            )
            return NonForwardableMessageEnforcer(
                identity_service=identity_service, registry=registry
            )

        # Register as singleton with factory
        register_singleton_if_absent(
            services,
            NonForwardableMessageEnforcer,
            implementation_factory=enforcer_factory,
        )

        # Register interface binding
        register_interface_and_implementation(
            services,
            cast(type, INonForwardableMessageEnforcer),
            NonForwardableMessageEnforcer,
            implementation_factory=enforcer_factory,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered NonForwardableMessageEnforcer")
    except ImportError as e:
        logger.warning(
            "Could not register non-forwardable enforcer service: %s", e, exc_info=True
        )
