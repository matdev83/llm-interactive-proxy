"""Gemini connector coordinator services registration.

Registers Gemini connector coordinator services for dependency injection.
These services are registered as transient (per-connector instance) with
factory functions that resolve dependencies from the DI container.
"""

from __future__ import annotations

import logging

from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_transient_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_gemini_coordinator_services(services: ServiceCollection) -> None:
    """Register Gemini connector coordinator services.

    This function registers coordinator services as transient (per-connector instance)
    with factory functions that resolve dependencies. Services are optional - connectors
    will create them locally if not registered in DI.

    **Important**: The factories in this module create coordinator instances with
    default dependencies (e.g., StandardCodeAssistEndpoint, empty public_to_internal_map).
    Connectors should always create their own coordinator instances with connector-specific
    dependencies (endpoint_config, public_to_internal_map, backend_name, etc.) rather than
    using DI-registered instances directly. The DI registration is primarily for:
    - Testing: Allows injecting test doubles without modifying production code
    - Optional injection: Connectors can resolve services if available, but fallback
      to local construction ensures backward compatibility

    Args:
        services: The service collection to register into
    """
    from src.connectors.gemini_base.credential_coordinator import (
        GeminiCredentialCoordinator,
    )
    from src.connectors.gemini_base.error_mapper import GeminiErrorMapper
    from src.connectors.gemini_base.file_watcher import FileWatcherState
    from src.connectors.gemini_base.interfaces import (
        ICredentialCoordinator,
        IErrorMapper,
    )
    from src.connectors.gemini_base.token_manager import TokenManager

    # Register credential coordinator (transient - per connector instance)
    # This service handles credential validation, refresh, and file watching.
    # It's generic enough to be registered via DI, as it relies on TokenManager
    # and FileWatcherState which are also DI services.
    def _credential_coordinator_factory(
        provider: IServiceProvider,
    ) -> GeminiCredentialCoordinator:
        """Factory for credential coordinator."""
        token_manager = provider.get_service(TokenManager)
        file_watcher_state = provider.get_service(FileWatcherState)
        return GeminiCredentialCoordinator(
            token_manager=token_manager,
            file_watcher_state=file_watcher_state,
        )

    register_transient_if_absent(
        services,
        GeminiCredentialCoordinator,
        implementation_factory=_credential_coordinator_factory,
    )
    register_transient_if_absent(
        services,
        ICredentialCoordinator,
        implementation_factory=lambda p: p.get_required_service(
            GeminiCredentialCoordinator
        ),
    )

    # Register error mapper (transient - per connector instance)
    # This service normalizes exceptions and is stateless/generic.
    register_transient_if_absent(services, GeminiErrorMapper)
    register_transient_if_absent(
        services,
        IErrorMapper,
        implementation_factory=lambda p: p.get_required_service(GeminiErrorMapper),
    )

    # Note: Connector-specific services are NOT registered here by default:
    # - IModelRegistry / GeminiModelRegistry
    # - IHealthCheckService / GeminiHealthCheckService
    # - IVtcWrapperBuilder / GeminiVtcWrapperBuilder
    #
    # These services require connector-specific configuration (public_to_internal_map,
    # backend_name, disable_health_checks, etc.) that varies by connector instance.
    # Registering them here with default values would cause the connector to inject
    # incorrect instances instead of creating its own correctly configured ones.
    #
    # The connector will automatically instantiate these services locally if they
    # are not found in the DI container.

    # Register supporting services that coordinators depend on

    # Note: ChatCompletionCoordinator is not registered here because it requires
    # connector-specific dependencies (ChatRequestPreparer, orchestrator, etc.)
    # that are created per-connector instance. The connector creates it lazily.

    # Register supporting services that coordinators depend on
    register_transient_if_absent(services, TokenManager)
    register_transient_if_absent(services, FileWatcherState)

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Registered Gemini connector coordinator services")
