"""
Session lifecycle and cancellation registrations.

Registers:
- EndOfSessionService / IEndOfSessionService
- SessionCancellationCoordinator / ISessionCancellationCoordinator
- ClientTerminationReasonMapper / IClientTerminationReasonMapper
- ClientEndOfSessionService / IClientEndOfSessionService
- SessionCancellationCleanupEosSubscriber
- ModelReplacementEosSubscriber
"""

from __future__ import annotations

import logging

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import (
    register_singleton_if_absent,
)
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_session_lifecycle_services(
    services: ServiceCollection,
    app_config: AppConfig | None,
) -> None:
    """Register all session lifecycle and cancellation services.

    Must be called BEFORE StreamNormalizer registration.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    _register_end_of_session_service(services, app_config)
    _register_session_cancellation_coordinator(services, app_config)
    _register_client_termination_reason_mapper(services, app_config)
    _register_client_end_of_session_service(services, app_config)
    _register_session_cancellation_cleanup_subscriber(services, app_config)


def _register_end_of_session_service(
    services: ServiceCollection, app_config: AppConfig | None
) -> None:
    """Register the End-of-Session service.

    This service must be registered before StreamNormalizer so that
    EndOfSessionStreamProcessor can resolve IEndOfSessionService.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration (required for EoS config)
    """
    from typing import cast

    from src.core.config.models.end_of_session import EndOfSessionConfig
    from src.core.interfaces.end_of_session_service_interface import (
        IEndOfSessionService,
    )
    from src.core.interfaces.event_bus_interface import IEventBus
    from src.core.services.end_of_session_service import EndOfSessionService

    # Check if app_config is provided (required for EoS config)
    # Note: EventBus should be registered in CoreServicesStage before streaming.register()
    # is called, so we don't need to check for it here. The factory will handle errors.
    if app_config is None:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "app_config not provided, skipping EndOfSessionService registration"
            )
        return

    def end_of_session_service_factory(
        provider: IServiceProvider,
    ) -> EndOfSessionService:
        # Get required dependencies - fail fast if not available
        # EventBus should ALWAYS be registered by CoreServicesStage before this runs
        event_bus: IEventBus = provider.get_required_service(cast(type, IEventBus))

        eos_config: EndOfSessionConfig = app_config.end_of_session

        # SessionMetricsRepository is registered in persistence.register(),
        # which runs after streaming.register(). Since factories are lazy,
        # this will only be resolved when EndOfSessionService is first used,
        # which happens after all registrations are complete.
        from src.core.database.repositories.usage_repository import (
            SessionMetricsRepository,
        )

        session_repo: SessionMetricsRepository = provider.get_required_service(
            SessionMetricsRepository
        )

        return EndOfSessionService(
            event_bus=event_bus,
            config=eos_config,
            session_repository=session_repo,
        )

    register_singleton_if_absent(
        services,
        EndOfSessionService,
        implementation_factory=end_of_session_service_factory,
    )
    register_singleton_if_absent(
        services,
        cast(type, IEndOfSessionService),
        implementation_factory=lambda p: p.get_required_service(EndOfSessionService),
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Registered EndOfSessionService in streaming registrations")


def _register_session_cancellation_coordinator(
    services: ServiceCollection, app_config: AppConfig | None = None
) -> None:
    """Register the SessionCancellationCoordinator.

    This coordinator maintains session-scoped cancellation state and provides
    cancellation gating to prevent new backend work after client termination.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration (not used, kept for signature consistency)
    """
    from typing import cast

    from src.core.interfaces.session_cancellation_coordinator_interface import (
        ISessionCancellationCoordinator,
    )
    from src.core.services.session_cancellation_coordinator import (
        SessionCancellationCoordinator,
    )

    def coordinator_factory(
        provider: IServiceProvider,
    ) -> SessionCancellationCoordinator:
        """Factory to create SessionCancellationCoordinator."""
        return SessionCancellationCoordinator()

    register_singleton_if_absent(
        services,
        SessionCancellationCoordinator,
        implementation_factory=coordinator_factory,
    )
    register_singleton_if_absent(
        services,
        cast(type, ISessionCancellationCoordinator),
        implementation_factory=lambda p: p.get_service(SessionCancellationCoordinator),  # type: ignore[arg-type]
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Registered SessionCancellationCoordinator in streaming registrations"
        )


def _register_client_termination_reason_mapper(
    services: ServiceCollection, app_config: AppConfig | None = None
) -> None:
    """Register the ClientTerminationReasonMapper.

    This mapper normalizes legacy cancellation markers and transport signals
    into standardized client termination reasons.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration (not used, kept for signature consistency)
    """
    from typing import cast

    from src.core.interfaces.client_termination_reason_mapper_interface import (
        IClientTerminationReasonMapper,
    )
    from src.core.services.client_termination_reason_mapper import (
        ClientTerminationReasonMapper,
    )

    def mapper_factory(
        provider: IServiceProvider,
    ) -> ClientTerminationReasonMapper:
        """Factory to create ClientTerminationReasonMapper."""
        return ClientTerminationReasonMapper()

    register_singleton_if_absent(
        services,
        ClientTerminationReasonMapper,
        implementation_factory=mapper_factory,
    )
    register_singleton_if_absent(
        services,
        cast(type, IClientTerminationReasonMapper),
        implementation_factory=lambda p: p.get_service(ClientTerminationReasonMapper),  # type: ignore[arg-type]
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Registered ClientTerminationReasonMapper in streaming registrations"
        )


def _register_client_end_of_session_service(
    services: ServiceCollection, app_config: AppConfig | None = None
) -> None:
    """Register the ClientEndOfSessionService.

    This service normalizes client termination signals, orchestrates cancellation,
    and ensures End-of-Session events are emitted for client-terminated sessions.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration (not used, kept for signature consistency)
    """
    from typing import cast

    from src.core.interfaces.client_end_of_session_service_interface import (
        IClientEndOfSessionService,
    )
    from src.core.interfaces.client_termination_reason_mapper_interface import (
        IClientTerminationReasonMapper,
    )
    from src.core.interfaces.end_of_session_service_interface import (
        IEndOfSessionService,
    )
    from src.core.interfaces.session_cancellation_coordinator_interface import (
        ISessionCancellationCoordinator,
    )
    from src.core.interfaces.session_metrics_initializer_interface import (
        ISessionMetricsInitializer,
    )
    from src.core.services.client_end_of_session_service import (
        ClientEndOfSessionService,
    )

    def service_factory(
        provider: IServiceProvider,
    ) -> ClientEndOfSessionService | None:
        """Factory to create ClientEndOfSessionService."""
        coordinator = provider.get_service(cast(type, ISessionCancellationCoordinator))
        if coordinator is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "ISessionCancellationCoordinator not available, "
                    "ClientEndOfSessionService will not be created"
                )
            return None

        metrics_initializer = provider.get_service(
            cast(type, ISessionMetricsInitializer)
        )
        if metrics_initializer is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "ISessionMetricsInitializer not available, "
                    "ClientEndOfSessionService will not be created"
                )
            return None

        eos_service = provider.get_service(cast(type, IEndOfSessionService))
        if eos_service is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "IEndOfSessionService not available, "
                    "ClientEndOfSessionService will not be created"
                )
            return None

        reason_mapper = provider.get_service(cast(type, IClientTerminationReasonMapper))
        if reason_mapper is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "IClientTerminationReasonMapper not available, "
                    "ClientEndOfSessionService will not be created"
                )
            return None

        return ClientEndOfSessionService(
            cancellation_coordinator=coordinator,
            metrics_initializer=metrics_initializer,
            eos_service=eos_service,
            reason_mapper=reason_mapper,
        )

    register_singleton_if_absent(
        services,
        ClientEndOfSessionService,
        implementation_factory=service_factory,  # type: ignore[arg-type]
    )
    register_singleton_if_absent(
        services,
        cast(type, IClientEndOfSessionService),
        implementation_factory=lambda p: p.get_service(ClientEndOfSessionService),  # type: ignore[arg-type]
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Registered ClientEndOfSessionService in streaming registrations")


def _register_session_cancellation_cleanup_subscriber(
    services: ServiceCollection, app_config: AppConfig | None = None
) -> None:
    """Register the SessionCancellationCleanupEosSubscriber.

    This subscriber listens for EoS events and cleans up cancellation state.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration (not used, kept for signature consistency)
    """
    from typing import cast

    from src.core.interfaces.event_bus_interface import IEventBus
    from src.core.interfaces.session_cancellation_coordinator_interface import (
        ISessionCancellationCoordinator,
    )
    from src.core.services.session_cancellation_cleanup_eos_subscriber import (
        SessionCancellationCleanupEosSubscriber,
    )

    def subscriber_factory(
        provider: IServiceProvider,
    ) -> SessionCancellationCleanupEosSubscriber | None:
        """Factory to create SessionCancellationCleanupEosSubscriber."""
        event_bus = provider.get_service(cast(type, IEventBus))
        if event_bus is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "IEventBus not available, "
                    "SessionCancellationCleanupEosSubscriber will not be created"
                )
            return None

        coordinator = provider.get_service(cast(type, ISessionCancellationCoordinator))
        if coordinator is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "ISessionCancellationCoordinator not available, "
                    "SessionCancellationCleanupEosSubscriber will not be created"
                )
            return None

        return SessionCancellationCleanupEosSubscriber(
            event_bus=event_bus, coordinator=coordinator
        )

    register_singleton_if_absent(
        services,
        SessionCancellationCleanupEosSubscriber,
        implementation_factory=subscriber_factory,  # type: ignore[arg-type]
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Registered SessionCancellationCleanupEosSubscriber in streaming registrations"
        )

    # Register ModelReplacementEosSubscriber
    from src.core.interfaces.model_replacement_service_interface import (
        IModelReplacementService,
    )
    from src.core.services.model_replacement_eos_subscriber import (
        ModelReplacementEosSubscriber,
    )

    def replacement_subscriber_factory(
        provider: IServiceProvider,
    ) -> ModelReplacementEosSubscriber | None:
        """Factory to create ModelReplacementEosSubscriber."""
        event_bus = provider.get_service(cast(type, IEventBus))
        if event_bus is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "IEventBus not available, "
                    "ModelReplacementEosSubscriber will not be created"
                )
            return None

        replacement_service = provider.get_service(cast(type, IModelReplacementService))
        if replacement_service is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "IModelReplacementService not available, "
                    "ModelReplacementEosSubscriber will not be created"
                )
            return None

        return ModelReplacementEosSubscriber(
            event_bus=event_bus, replacement_service=replacement_service
        )

    register_singleton_if_absent(
        services,
        ModelReplacementEosSubscriber,
        implementation_factory=replacement_subscriber_factory,  # type: ignore[arg-type]
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Registered ModelReplacementEosSubscriber in streaming registrations"
        )
