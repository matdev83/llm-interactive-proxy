"""
Foundational core services registration helper.

Registers:
- AppConfig and IConfig
- EventBus and IEventBus
- Session services
- Application state services
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any, cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import (
    register_singleton_if_absent,
)
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_app_config(
    services: ServiceCollection, app_config: AppConfig | None
) -> None:
    """Register AppConfig and IConfig interface."""
    from src.core.interfaces.configuration_interface import IConfig

    if app_config is not None:
        register_singleton_if_absent(services, AppConfig, instance=app_config)
        try:
            register_singleton_if_absent(
                services, IConfig, instance=app_config
            )  # type: ignore[type-abstract]
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to register IConfig interface: %s", e, exc_info=True
                )
    else:
        # Register default AppConfig for testing and basic functionality
        default_config = AppConfig()
        register_singleton_if_absent(services, AppConfig, instance=default_config)
        try:
            register_singleton_if_absent(
                services, IConfig, instance=default_config
            )  # type: ignore[type-abstract]
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to register default IConfig interface: %s", e, exc_info=True
                )


def register_event_bus(services: ServiceCollection) -> None:
    """Register EventBus and IEventBus interface.

    EventBus must be registered early as it's required by streaming services
    (e.g., EndOfSessionService) and other core services.
    """
    from src.core.interfaces.event_bus_interface import IEventBus
    from src.core.services.event_bus import EventBus

    def event_bus_factory(provider: IServiceProvider) -> EventBus:
        return EventBus()

    register_singleton_if_absent(
        services, EventBus, implementation_factory=event_bus_factory
    )
    try:
        register_singleton_if_absent(
            services,
            IEventBus,
            implementation_factory=lambda p: p.get_required_service(EventBus),
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered EventBus and IEventBus")
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register IEventBus interface: %s", e, exc_info=True
            )


def register_session_services(services: ServiceCollection) -> None:
    """Register session-related services."""
    from src.core.interfaces.session_resolver_interface import ISessionResolver
    from src.core.interfaces.session_service_interface import ISessionService
    from src.core.repositories.in_memory_session_repository import (
        InMemorySessionRepository,
    )
    from src.core.services.session_resolver_service import DefaultSessionResolver
    from src.core.services.session_service_impl import SessionService

    # Register session resolver
    register_singleton_if_absent(services, DefaultSessionResolver)
    register_singleton_if_absent(
        services, ISessionResolver, implementation_type=DefaultSessionResolver  # type: ignore[type-abstract]
    )

    # Register session service
    def _session_service_factory(provider: IServiceProvider) -> SessionService:
        repository = InMemorySessionRepository()
        return SessionService(repository)

    register_singleton_if_absent(
        services, SessionService, implementation_factory=_session_service_factory
    )

    try:
        register_singleton_if_absent(
            services,
            ISessionService,
            implementation_factory=_session_service_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register ISessionService interface: %s", e, exc_info=True
            )


def _register_notification_service(services: ServiceCollection) -> None:
    """Register NotificationService with INotificationService interface binding."""
    try:
        from src.core.interfaces.notification_service_interface import (
            INotificationService,
        )
        from src.core.services.notification_service import NotificationService

        def notification_service_factory(
            provider: IServiceProvider,
        ) -> NotificationService:
            """Factory for creating NotificationService with config."""
            from src.core.services.notifications.providers.desktop_notifier import (
                DesktopNotifierProvider,
            )

            config = provider.get_service(AppConfig)
            host = "127.0.0.1"
            notif_config = None

            if config is not None:
                host = config.host
                notif_config = config.notifications

            if notif_config is None:
                from src.core.config.models.notification import NotificationConfig

                notif_config = NotificationConfig()

            return NotificationService(
                config=notif_config, host=host, provider=DesktopNotifierProvider()
            )

        register_singleton_if_absent(
            services,
            NotificationService,
            implementation_factory=notification_service_factory,
        )

        # Register INotificationService interface binding
        def inotification_service_factory(
            provider: IServiceProvider,
        ) -> NotificationService:
            return provider.get_required_service(NotificationService)

        register_singleton_if_absent(
            services,
            INotificationService,
            implementation_factory=inotification_service_factory,
        )
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Could not register NotificationService: %s", e, exc_info=True
            )


def register_application_state_services(services: ServiceCollection) -> None:
    """Register application state services."""
    from src.core.interfaces.app_settings_interface import IAppSettings
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.state_provider_interface import (
        ISecureStateAccess,
        ISecureStateModification,
    )
    from src.core.services.app_settings_service import AppSettings
    from src.core.services.application_state_service import ApplicationStateService
    from src.core.services.secure_command_factory import SecureCommandFactory
    from src.core.services.secure_state_service import SecureStateService

    # Register ApplicationStateService
    def _application_state_factory(
        provider: IServiceProvider,
    ) -> ApplicationStateService:
        return ApplicationStateService()

    register_singleton_if_absent(services, ApplicationStateService)
    try:
        register_singleton_if_absent(
            services,
            IApplicationState,
            implementation_factory=_application_state_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register IApplicationState interface: %s", e, exc_info=True
            )

    # Register AppSettings
    def _app_settings_factory(provider: IServiceProvider) -> AppSettings:
        app_state: Any | None = None
        try:
            app_state_service: IApplicationState | None = provider.get_service(
                ApplicationStateService
            )
            if app_state_service:
                app_state = app_state_service.get_setting("service_provider")
        except Exception as e:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to get service_provider from app_state_service: %s",
                    e,
                    exc_info=True,
                )
            app_state = None
        return AppSettings(app_state)

    register_singleton_if_absent(
        services, AppSettings, implementation_factory=_app_settings_factory
    )
    try:
        register_singleton_if_absent(
            services,
            IAppSettings,
            implementation_factory=_app_settings_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register IAppSettings interface: %s", e, exc_info=True
            )

    # Register SecureStateService
    def _secure_state_factory(provider: IServiceProvider) -> SecureStateService:
        app_state = provider.get_required_service(ApplicationStateService)
        return SecureStateService(app_state)

    register_singleton_if_absent(
        services, SecureStateService, implementation_factory=_secure_state_factory
    )
    try:
        register_singleton_if_absent(
            services,
            ISecureStateAccess,
            implementation_factory=_secure_state_factory,  # type: ignore[type-abstract]
        )
        register_singleton_if_absent(
            services,
            ISecureStateModification,
            implementation_factory=_secure_state_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register secure state interfaces: %s", e, exc_info=True
            )

    # Register SecureCommandFactory
    def _secure_command_factory(provider: IServiceProvider) -> SecureCommandFactory:
        secure_state = provider.get_required_service(SecureStateService)
        return SecureCommandFactory(
            state_reader=secure_state, state_modifier=secure_state
        )

    register_singleton_if_absent(
        services, SecureCommandFactory, implementation_factory=_secure_command_factory
    )

    # Register ConversationFingerprintService
    from src.core.services.conversation_fingerprint_service import (
        ConversationFingerprintService,
    )

    register_singleton_if_absent(services, ConversationFingerprintService)

    # Register ToolCallRepairService
    _register_tool_call_repair_service(services)

    # Register HistoryCompactionService
    from src.core.interfaces.history_compaction_interface import (
        IHistoryCompactionService,
    )
    from src.core.services.history_compaction_service import HistoryCompactionService

    register_singleton_if_absent(services, HistoryCompactionService)
    try:
        register_singleton_if_absent(
            services,
            IHistoryCompactionService,
            implementation_factory=lambda provider: provider.get_required_service(
                HistoryCompactionService
            ),  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register IHistoryCompactionService interface: %s",
                e,
                exc_info=True,
            )

    # Register NotificationService
    _register_notification_service(services)

    # Register SessionManager
    from src.core.interfaces.repositories_interface import ISessionRepository
    from src.core.interfaces.session_manager_interface import ISessionManager
    from src.core.services.session_manager_service import SessionManager

    def _session_manager_factory(provider: IServiceProvider) -> SessionManager:
        from src.core.interfaces.session_resolver_interface import ISessionResolver
        from src.core.interfaces.session_service_interface import ISessionService
        from src.core.services.conversation_fingerprint_service import (
            ConversationFingerprintService,
        )

        session_service = provider.get_required_service(cast(Any, ISessionService))
        session_resolver = provider.get_required_service(cast(Any, ISessionResolver))
        session_repository = provider.get_service(cast(Any, ISessionRepository))
        fingerprint_service = provider.get_required_service(
            ConversationFingerprintService
        )
        return SessionManager(
            session_service,
            session_resolver,
            session_repository=session_repository,
            fingerprint_service=fingerprint_service,
        )

    register_singleton_if_absent(
        services, SessionManager, implementation_factory=_session_manager_factory
    )
    try:
        register_singleton_if_absent(
            services,
            ISessionManager,
            implementation_factory=_session_manager_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register ISessionManager interface: %s", e, exc_info=True
            )


def register_time_source(services: ServiceCollection) -> None:
    """Register time source service."""
    from src.core.interfaces.time_source_interface import ITimeSource
    from src.core.services.time_source_service import TimeSource

    # Register TimeSource as singleton
    register_singleton_if_absent(services, TimeSource)
    try:
        # Register ITimeSource interface to resolve to same instance
        def _time_source_factory(provider: IServiceProvider) -> TimeSource:
            return provider.get_required_service(TimeSource)

        register_singleton_if_absent(
            services,
            ITimeSource,
            implementation_factory=_time_source_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register ITimeSource interface: %s", e, exc_info=True
            )


def _register_tool_call_repair_service(services: ServiceCollection) -> None:
    """Register ToolCallRepairService with IToolCallRepairService interface binding."""
    try:
        from src.core.interfaces.tool_call_repair_service_interface import (
            IToolCallRepairService,
        )
        from src.core.services.tool_call_repair_service import ToolCallRepairService

        def tool_repair_factory(provider: IServiceProvider) -> ToolCallRepairService:
            """Factory for creating ToolCallRepairService with config."""
            config = provider.get_service(AppConfig)
            cap = 64 * 1024
            if config is not None:
                with contextlib.suppress(Exception):
                    cap = int(config.session.tool_call_repair_buffer_cap_bytes)
            return ToolCallRepairService(max_buffer_bytes=cap)

        register_singleton_if_absent(
            services, ToolCallRepairService, implementation_factory=tool_repair_factory
        )

        # Register IToolCallRepairService interface binding
        def itool_call_repair_factory(
            provider: IServiceProvider,
        ) -> ToolCallRepairService:
            return provider.get_required_service(ToolCallRepairService)

        register_singleton_if_absent(
            services,
            IToolCallRepairService,
            implementation_factory=itool_call_repair_factory,
        )
    except ImportError as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Could not register ToolCallRepairService: %s", e, exc_info=True
            )
