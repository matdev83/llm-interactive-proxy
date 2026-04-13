"""
Tests for core services registrar.

These tests verify that:
- Foundational services are registered correctly
- Request processing orchestration services are registered correctly
- Phase components are registered correctly
- Integration with orchestrator works
- Idempotency is preserved
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations import core, persistence, streaming
from src.core.interfaces.app_settings_interface import IAppSettings
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_interface import (
    IBackendRequestManager,
)
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.command_service_interface import ICommandService
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.interfaces.request_processor_internal import (
    IBackendExecutor,
    IBackendPreparer,
    ICommandHandler,
    IRequestSideEffects,
    IRequestTransformPipeline,
    ISessionEnricher,
)
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.time_source_interface import ITimeSource
from src.core.services.application_state_service import ApplicationStateService
from src.core.services.backend_processor import BackendProcessor
from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.services.request_processor_service import RequestProcessor
from src.core.services.session_service_impl import SessionService
from src.core.services.time_source_service import TimeSource


class TestCoreRegistrarFoundationalServices:
    """Test foundational services registration."""

    def test_app_config_registration_with_provided_config(self) -> None:
        """Verify AppConfig registration when config is provided."""
        services = ServiceCollection()
        config = AppConfig()

        core.register(services, config)
        provider = services.build_service_provider()

        resolved_config = provider.get_service(AppConfig)
        assert resolved_config is not None
        assert resolved_config is config

    def test_app_config_registration_without_provided_config(self) -> None:
        """Verify AppConfig registration when config is None."""
        services = ServiceCollection()

        core.register(services, None)
        provider = services.build_service_provider()

        resolved_config = provider.get_service(AppConfig)
        assert resolved_config is not None
        assert isinstance(resolved_config, AppConfig)

    def test_iconfig_interface_registration(self) -> None:
        """Verify IConfig interface is registered."""
        services = ServiceCollection()
        config = AppConfig()

        core.register(services, config)
        provider = services.build_service_provider()

        resolved_iconfig = provider.get_service(cast(type, IConfig))
        assert resolved_iconfig is not None

    def test_time_source_registration(self) -> None:
        """Verify TimeSource and ITimeSource are registered."""
        services = ServiceCollection()
        config = AppConfig()

        core.register(services, config)
        provider = services.build_service_provider()

        time_source = provider.get_service(TimeSource)
        assert time_source is not None
        assert isinstance(time_source, TimeSource)

        itime_source = provider.get_service(cast(type, ITimeSource))
        assert itime_source is not None
        assert isinstance(itime_source, ITimeSource)
        assert itime_source is time_source  # Should be same instance (singleton)

    def test_time_source_is_singleton(self) -> None:
        """Verify TimeSource is registered as singleton."""
        services = ServiceCollection()
        config = AppConfig()

        core.register(services, config)
        provider = services.build_service_provider()

        time_source1 = provider.get_service(TimeSource)
        time_source2 = provider.get_service(TimeSource)

        assert time_source1 is not None
        assert time_source2 is not None
        assert time_source1 is time_source2  # Same instance

    def test_session_service_registration(self) -> None:
        """Verify SessionService and ISessionService are registered."""
        services = ServiceCollection()
        config = AppConfig()

        core.register(services, config)
        provider = services.build_service_provider()

        session_service = provider.get_service(SessionService)
        assert session_service is not None

        isession_service = provider.get_service(cast(type, ISessionService))
        assert isession_service is not None

    def test_session_resolver_registration(self) -> None:
        """Verify session resolver is registered."""
        services = ServiceCollection()
        config = AppConfig()

        core.register(services, config)
        provider = services.build_service_provider()

        resolver = provider.get_service(cast(type, ISessionResolver))
        assert resolver is not None

    def test_application_state_registration(self) -> None:
        """Verify ApplicationStateService and IApplicationState are registered."""
        services = ServiceCollection()
        config = AppConfig()

        core.register(services, config)
        provider = services.build_service_provider()

        app_state = provider.get_service(ApplicationStateService)
        assert app_state is not None

        iapp_state = provider.get_service(cast(type, IApplicationState))
        assert iapp_state is not None

    def test_app_settings_registration(self) -> None:
        """Verify AppSettings and IAppSettings are registered."""
        services = ServiceCollection()
        config = AppConfig()

        core.register(services, config)
        provider = services.build_service_provider()

        app_settings = provider.get_service(cast(type, IAppSettings))
        assert app_settings is not None

    def test_command_service_registration(self) -> None:
        """Verify CommandService and ICommandService are registered."""
        services = ServiceCollection()
        config = AppConfig()

        core.register(services, config)
        provider = services.build_service_provider()

        command_service = provider.get_service(cast(type, ICommandService))
        assert command_service is not None

    def test_command_processor_registration(self) -> None:
        """Verify CommandProcessor and ICommandProcessor are registered."""
        services = ServiceCollection()
        config = AppConfig()

        core.register(services, config)
        provider = services.build_service_provider()

        command_processor = provider.get_service(cast(type, ICommandProcessor))
        assert command_processor is not None


class TestCoreRegistrarRequestProcessing:
    """Test request processing orchestration registration."""

    def test_request_processor_registration(self) -> None:
        """Verify RequestProcessor and IRequestProcessor are registered."""
        services = ServiceCollection()
        config = AppConfig()

        # Register dependencies required by RequestProcessor
        from src.core.interfaces.backend_request_manager_interface import (
            IBackendRequestManager,
        )
        from src.core.interfaces.backend_service_interface import IBackendService
        from src.core.interfaces.response_manager_interface import IResponseManager
        from src.core.interfaces.session_manager_interface import ISessionManager
        from src.core.services.backend_request_manager_service import (
            BackendRequestManager,
        )
        from src.core.services.backend_service import BackendService
        from src.core.services.response_manager_service import ResponseManager
        from src.core.services.session_manager_service import SessionManager

        # Register mocked dependencies
        services.add_instance(IBackendService, MagicMock(spec=BackendService))
        services.add_instance(
            IBackendRequestManager, MagicMock(spec=BackendRequestManager)
        )
        services.add_instance(IResponseManager, MagicMock(spec=ResponseManager))

        def session_manager_factory(provider) -> SessionManager:
            from src.core.services.conversation_fingerprint_service import (
                ConversationFingerprintService,
            )

            session_service = provider.get_required_service(cast(type, ISessionService))
            session_resolver = provider.get_required_service(
                cast(type, ISessionResolver)
            )
            fingerprint_service = provider.get_required_service(
                ConversationFingerprintService
            )
            return SessionManager(
                session_service,
                session_resolver,
                fingerprint_service=fingerprint_service,
            )

        services.add_singleton(
            SessionManager, implementation_factory=session_manager_factory
        )
        services.add_singleton(
            cast(type, ISessionManager), implementation_factory=session_manager_factory
        )

        core.register(services, config)
        provider = services.build_service_provider()

        request_processor = provider.get_service(RequestProcessor)
        assert request_processor is not None

        irequest_processor = provider.get_service(cast(type, IRequestProcessor))
        assert irequest_processor is not None

    def test_backend_processor_registration(self) -> None:
        """Verify BackendProcessor and IBackendProcessor are registered."""
        services = ServiceCollection()
        config = AppConfig()

        # Register dependencies
        from src.core.interfaces.backend_service_interface import IBackendService
        from src.core.services.backend_service import BackendService

        services.add_instance(IBackendService, MagicMock(spec=BackendService))

        core.register(services, config)
        provider = services.build_service_provider()

        backend_processor = provider.get_service(BackendProcessor)
        assert backend_processor is not None

        ibackend_processor = provider.get_service(cast(type, IBackendProcessor))
        assert ibackend_processor is not None

    def test_backend_request_manager_registration(self) -> None:
        """Verify BackendRequestManager and IBackendRequestManager are registered."""
        services = ServiceCollection()
        config = AppConfig()

        # Register dependencies
        from src.core.interfaces.backend_service_interface import IBackendService
        from src.core.interfaces.quality_verifier_service_interface import (
            IQualityVerifierServiceFactory,
        )
        from src.core.interfaces.response_processor_interface import IResponseProcessor
        from src.core.interfaces.wire_capture_interface import IWireCapture
        from src.core.services.backend_service import BackendService

        services.add_instance(IBackendService, MagicMock(spec=BackendService))
        services.add_instance(IResponseProcessor, MagicMock())
        services.add_instance(IWireCapture, MagicMock())
        services.add_instance(IQualityVerifierServiceFactory, MagicMock())

        core.register(services, config)
        provider = services.build_service_provider()

        backend_request_manager = provider.get_service(BackendRequestManager)
        assert backend_request_manager is not None

        ibackend_request_manager = provider.get_service(
            cast(type, IBackendRequestManager)
        )
        assert ibackend_request_manager is not None

    def test_phase_components_registration(self) -> None:
        """Verify all phase components are registered."""
        services = ServiceCollection()
        config = AppConfig()

        # Register dependencies required by phase components
        from src.core.interfaces.backend_service_interface import IBackendService
        from src.core.services.backend_service import BackendService

        services.add_instance(IBackendService, MagicMock(spec=BackendService))

        # Register additional dependencies required by phase components
        from src.core.interfaces.quality_verifier_service_interface import (
            IQualityVerifierServiceFactory,
        )
        from src.core.interfaces.wire_capture_interface import IWireCapture

        services.add_instance(IQualityVerifierServiceFactory, MagicMock())
        services.add_instance(IWireCapture, MagicMock())

        # Register EventBus (required by EoS services)
        from typing import cast

        from src.core.interfaces.di_interface import IServiceProvider
        from src.core.interfaces.event_bus_interface import IEventBus
        from src.core.services.event_bus import EventBus

        def event_bus_factory(provider: IServiceProvider) -> EventBus:
            return EventBus()

        services.add_singleton(EventBus, implementation_factory=event_bus_factory)
        services.add_singleton(
            cast(type, IEventBus),
            implementation_factory=lambda p: p.get_required_service(EventBus),
        )

        core.register(services, config)
        persistence.register(services, config)
        streaming.register(services, config)
        provider = services.build_service_provider()

        # Verify phase components are registered
        session_enricher = provider.get_service(cast(type, ISessionEnricher))
        assert session_enricher is not None

        request_side_effects = provider.get_service(cast(type, IRequestSideEffects))
        assert request_side_effects is not None

        command_handler = provider.get_service(cast(type, ICommandHandler))
        assert command_handler is not None

        backend_preparer = provider.get_service(cast(type, IBackendPreparer))
        assert backend_preparer is not None

        transform_pipeline = provider.get_service(cast(type, IRequestTransformPipeline))
        assert transform_pipeline is not None

        backend_executor = provider.get_service(cast(type, IBackendExecutor))
        assert backend_executor is not None


class TestCoreRegistrarIdempotency:
    """Test registrar idempotency."""

    def test_multiple_calls_dont_override(self) -> None:
        """Verify multiple calls to register don't override existing registrations."""
        services = ServiceCollection()
        config = AppConfig()

        # First registration
        core.register(services, config)
        provider1 = services.build_service_provider()
        app_config1 = provider1.get_service(AppConfig)

        # Second registration (should be idempotent)
        core.register(services, config)
        provider2 = services.build_service_provider()
        app_config2 = provider2.get_service(AppConfig)

        # Should resolve to same instance
        assert app_config1 is app_config2

    def test_registrar_can_run_on_empty_container(self) -> None:
        """Verify registrar runs without errors on empty container."""
        services = ServiceCollection()
        config = AppConfig()

        # Should not raise
        core.register(services, config)
        core.register(services, None)  # Should also work with None
