"""
Core services initialization stage.

This stage registers fundamental services that have minimal dependencies:
- Configuration services
- Session management
- Logging utilities
- Basic repositories
"""

# type: ignore[unreachable]
from __future__ import annotations

import contextlib
import logging

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.session_resolver_interface import ISessionResolver

# from src.core.interfaces.secure_state_interface import ISecureStateService # Removed unresolved import
from src.core.interfaces.streaming_response_processor_interface import (
    IStreamNormalizer as IProcessingStreamNormalizer,
)
from src.core.services.application_state_service import ApplicationStateService
from src.core.services.intelligent_session_resolver import IntelligentSessionResolver
from src.core.services.response_processor_service import ResponseProcessor
from src.core.services.secure_state_service import SecureStateService
from src.core.services.tool_call_repair_service import ToolCallRepairService

from .base import InitializationStage

logger = logging.getLogger(__name__)


class CoreServicesStage(InitializationStage):
    """
    Stage for registering core services with minimal dependencies.

    This stage registers:
    - AppConfig as a singleton instance
    - Session repository and service
    - Session resolver
    - Basic logging and configuration services
    """

    @property
    def name(self) -> str:
        return "core_services"

    def get_dependencies(self) -> list[str]:
        return ["infrastructure"]

    def get_description(self) -> str:
        return "Register core services (config, session, logging)"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register core services that have no external dependencies."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Initializing core services...")

        # Register AppConfig as singleton instance
        services.add_instance(AppConfig, config)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered AppConfig instance")

        # Register EventBus early for EoS services
        self._register_event_bus(services)

        # Register ApplicationStateService
        services.add_singleton(ApplicationStateService)
        services.add_singleton(IApplicationState, ApplicationStateService)

        # Register ToolCallRepairService as a singleton with configured buffer cap
        def _tool_repair_factory(
            provider: IServiceProvider,
        ) -> ToolCallRepairService:  # Modified to accept provider for consistency
            _config: AppConfig = provider.get_required_service(
                AppConfig
            )  # Resolve config from provider
            cap = 64 * 1024
            with contextlib.suppress(Exception):
                cap = int(_config.session.tool_call_repair_buffer_cap_bytes)
            return ToolCallRepairService(max_buffer_bytes=cap)

        services.add_singleton(
            ToolCallRepairService, implementation_factory=_tool_repair_factory
        )

        # Register IToolCallRepairService interface binding
        try:
            from typing import cast

            from src.core.interfaces.tool_call_repair_service_interface import (
                IToolCallRepairService,
            )

            def itool_call_repair_factory(
                provider: IServiceProvider,
            ) -> ToolCallRepairService:
                return provider.get_required_service(ToolCallRepairService)

            services.add_singleton(
                cast(type, IToolCallRepairService),
                implementation_factory=itool_call_repair_factory,
            )
        except ImportError as e:
            logger.warning("Could not register IToolCallRepairService interface: %s", e)

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Registered ToolCallRepairService with cap=%d bytes",
                int(
                    getattr(config.session, "tool_call_repair_buffer_cap_bytes", 65536)
                ),
            )

        # Register ResponseProcessor as a singleton
        # ResponseProcessor is registered in services.py using unified pipeline
        # The factory below is kept for reference but not used
        def _response_processor_factory_reference(
            provider: IServiceProvider,
        ) -> ResponseProcessor:
            """Factory reference - actual registration is in services.py."""
            app_state: IApplicationState = provider.get_required_service(
                IApplicationState  # type: ignore[type-abstract]
            )
            stream_normalizer: (
                IProcessingStreamNormalizer
            ) = provider.get_required_service(
                IProcessingStreamNormalizer  # type: ignore[type-abstract]
            )
            # ResponseProcessor now uses unified pipeline - no separate middleware manager
            return ResponseProcessor(
                app_state=app_state,
                response_parser=provider.get_required_service(IResponseParser),  # type: ignore[type-abstract]
                stream_normalizer=stream_normalizer,
            )

        # Suppress unused variable warning - this is intentionally kept as documentation
        _ = _response_processor_factory_reference

        # Register session repository
        self._register_session_repository(services)

        # Register session service
        self._register_session_service(services)

        # Register session resolver
        self._register_session_resolver(services, config)  # Re-added config parameter

        if logger.isEnabledFor(logging.INFO):
            logger.info("Core services initialized successfully")

    def _register_session_repository(self, services: ServiceCollection) -> None:
        """Register session repository services."""
        try:
            from src.core.interfaces.repositories_interface import ISessionRepository
            from src.core.repositories.in_memory_session_repository import (
                InMemorySessionRepository,
            )

            # Register concrete implementation
            services.add_singleton(InMemorySessionRepository)

            # Register interface binding
            from typing import cast

            services.add_singleton(
                cast(type, ISessionRepository), InMemorySessionRepository
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered session repository services")
        except ImportError as e:  # type: ignore[misc]
            logger.warning("Could not register session repository: %s", e)

    def _register_session_service(self, services: ServiceCollection) -> None:
        """Register session service with dependency injection."""
        try:
            from src.core.interfaces.repositories_interface import ISessionRepository
            from src.core.interfaces.session_service_interface import ISessionService
            from src.core.services.session_service_impl import SessionService

            def session_service_factory(provider: IServiceProvider) -> SessionService:
                """Factory function for creating SessionService with dependencies."""
                from typing import cast

                repo: ISessionRepository = provider.get_required_service(
                    cast(type, ISessionRepository)
                )
                return SessionService(repo)

            # Register concrete implementation with factory
            services.add_singleton(
                SessionService, implementation_factory=session_service_factory
            )

            # Register interface binding with same factory
            from typing import cast

            services.add_singleton(
                cast(type, ISessionService),
                implementation_factory=session_service_factory,
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered session service with factory")
        except ImportError as e:  # type: ignore[misc]
            logger.warning("Could not register session service: %s", e)

    def _register_session_resolver(
        self,
        services: ServiceCollection,
        config: AppConfig,  # Re-added config parameter
    ) -> None:
        """Register session resolver as singleton instance."""
        try:
            from typing import cast

            from src.core.interfaces.repositories_interface import ISessionRepository
            from src.core.services.conversation_fingerprint_service import (
                ConversationFingerprintService,
            )

            # Register ConversationFingerprintService as singleton
            services.add_singleton(ConversationFingerprintService)

            def session_resolver_factory(
                provider: IServiceProvider,
            ) -> IntelligentSessionResolver:
                """Factory for creating IntelligentSessionResolver with dependencies."""
                cfg: AppConfig = provider.get_required_service(AppConfig)
                session_repo: ISessionRepository = provider.get_required_service(
                    cast(type, ISessionRepository)
                )
                fingerprint_service: ConversationFingerprintService = (
                    provider.get_required_service(ConversationFingerprintService)
                )
                return IntelligentSessionResolver(
                    session_repository=session_repo,
                    config=cfg,
                    fingerprint_service=fingerprint_service,
                )

            # Register as singleton instance using factory
            services.add_singleton(
                IntelligentSessionResolver,
                implementation_factory=session_resolver_factory,
            )

            services.add_singleton(
                cast(type, ISessionResolver),
                implementation_factory=session_resolver_factory,
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered intelligent session resolver instance")

            # from src.core.services.secure_state_service import SecureStateService # Already imported

            # Register SecureStateService with a factory
            def secure_state_factory(provider: IServiceProvider) -> SecureStateService:
                app_state: IApplicationState = provider.get_required_service(
                    ApplicationStateService
                )
                return SecureStateService(app_state)

            services.add_singleton(
                SecureStateService, implementation_factory=secure_state_factory
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered SecureStateService with factory")
        except ImportError as e:  # type: ignore[misc]
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Could not register session resolver or SecureStateService: {e}"
                )

        # Register core services from DI services module

        try:
            from src.core.di.services import register_core_services

            register_core_services(services, config)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered core services from DI module")
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Failed to register core services from DI module: %s",
                    e,
                    exc_info=True,
                )
            raise

        # Register streaming and tooling services via registrars
        # These are needed for services like IResponseParser, IStreamNormalizer, etc.
        try:
            from src.core.di.registrations import streaming, tooling

            streaming.register(services, config)
            tooling.register(services, config)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered streaming and tooling services via registrars")
        except Exception as e:
            logger.warning(
                "Could not register streaming/tooling services: %s",
                e,
                exc_info=True,
            )

        # Register connection activity tracker (if enabled)
        self._register_activity_tracker(services, config)

        # Register wire capture service
        self._register_wire_capture_service(services)

        # Register usage tracking services
        self._register_usage_tracking_services(services, config)

        # Register usage normalization service
        self._register_usage_normalization_service(services)

    def _register_activity_tracker(
        self, services: ServiceCollection, config: AppConfig
    ) -> None:
        """Register connection activity tracker service.

        The activity tracker provides real-time visibility into active connections
        through backend connectors with RX/TX byte counters per session.

        This feature is disabled by default for performance. Enable via:
        - CLI: --enable-activity-tracking
        - Env: ENABLE_ACTIVITY_TRACKING=1
        - Config: enable_activity_tracking: true
        """
        # Check if activity tracking is enabled
        if not getattr(config, "enable_activity_tracking", False):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Activity tracking disabled (enable_activity_tracking=%s)",
                    getattr(config, "enable_activity_tracking", False),
                )
            return

        try:
            from src.core.interfaces.activity_tracker_interface import (
                IConnectionActivityTracker,
            )
            from src.core.services.connection_activity_tracker import (
                ConnectionActivityTracker,
                get_activity_tracker,
            )

            # Register the global singleton instance
            def activity_tracker_factory(
                provider: IServiceProvider,
            ) -> ConnectionActivityTracker:
                return get_activity_tracker()

            services.add_singleton(
                ConnectionActivityTracker,
                implementation_factory=activity_tracker_factory,
            )
            services.add_singleton(
                IConnectionActivityTracker,
                implementation_factory=activity_tracker_factory,
            )

            if logger.isEnabledFor(logging.INFO):
                logger.info("Activity tracking enabled - connection monitoring active")

            # Register the cleanup scheduler for the activity tracker
            try:
                from src.core.interfaces.activity_tracker_interface import (
                    IConnectionActivityTracker,
                )
                from src.core.services.connection_tracker_cleanup_scheduler import (
                    ConnectionTrackerCleanupScheduler,
                )

                def cleanup_scheduler_factory(
                    provider: IServiceProvider,
                ) -> ConnectionTrackerCleanupScheduler:
                    from src.core.services.connection_activity_tracker import (
                        ConnectionActivityTracker,
                    )

                    activity_tracker = provider.get_required_service(
                        ConnectionActivityTracker
                    )
                    # Use 5-minute interval by default (matches stale timeout)
                    return ConnectionTrackerCleanupScheduler(
                        activity_tracker=activity_tracker,
                        cleanup_interval_seconds=300,
                    )

                services.add_singleton(
                    ConnectionTrackerCleanupScheduler,
                    implementation_factory=cleanup_scheduler_factory,
                )

                if logger.isEnabledFor(logging.INFO):
                    logger.info("Connection tracker cleanup scheduler registered")
            except ImportError as e:
                logger.warning(
                    "Could not register connection tracker cleanup scheduler: %s", e
                )

        except ImportError as e:
            logger.warning("Could not register activity tracker service: %s", e)

    def _register_wire_capture_service(self, services: ServiceCollection) -> None:
        """Register wire capture service.

        Selects between BufferedWireCapture (JSON) and CborWireCaptureService (CBOR)
        based on configuration. CBOR capture is preferred when cbor_capture_dir is set.
        """
        try:
            from src.core.interfaces.wire_capture_interface import IWireCapture
            from src.core.services.buffered_wire_capture_service import (
                BufferedWireCapture,
            )

            def wire_capture_factory(
                provider: IServiceProvider,
            ) -> IWireCapture:
                config = provider.get_required_service(AppConfig)
                logging_cfg = getattr(config, "logging", None)
                cbor_capture_dir = (
                    getattr(logging_cfg, "cbor_capture_dir", None)
                    if logging_cfg
                    else None
                )

                # Use CBOR capture if directory is configured
                if cbor_capture_dir:
                    from src.core.services.cbor_wire_capture_service import (
                        CborWireCaptureService,
                    )

                    cbor_session_id = (
                        getattr(logging_cfg, "cbor_capture_session_id", None)
                        if logging_cfg
                        else None
                    )
                    logger.info("Using CBOR wire capture: %s", cbor_capture_dir)
                    return CborWireCaptureService(
                        config=config,
                        capture_dir=cbor_capture_dir,
                        session_id=cbor_session_id,
                    )

                # Fall back to JSON-based buffered capture
                return BufferedWireCapture(config)

            services.add_singleton(
                IWireCapture, implementation_factory=wire_capture_factory
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered wire capture service")

            # Register WireCaptureEosSubscriber
            def wire_capture_eos_subscriber_factory(
                provider: IServiceProvider,
            ) -> WireCaptureEosSubscriber:
                """Factory to create WireCaptureEosSubscriber."""
                from typing import cast

                from src.core.interfaces.event_bus_interface import IEventBus
                from src.core.services.wire_capture_eos_subscriber import (
                    WireCaptureEosSubscriber,
                )

                event_bus: IEventBus = provider.get_required_service(
                    cast(type, IEventBus)
                )
                wire_capture: IWireCapture = provider.get_required_service(
                    cast(type, IWireCapture)
                )
                return WireCaptureEosSubscriber(
                    event_bus=event_bus, wire_capture=wire_capture
                )

            try:
                from src.core.services.wire_capture_eos_subscriber import (
                    WireCaptureEosSubscriber,
                )

                services.add_singleton(
                    WireCaptureEosSubscriber,
                    implementation_factory=wire_capture_eos_subscriber_factory,
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Registered WireCaptureEosSubscriber")
            except ImportError:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "WireCaptureEosSubscriber not available, skipping registration"
                    )
        except ImportError as e:
            logger.warning("Could not register wire capture service: %s", e)

    def _register_usage_tracking_services(
        self, services: ServiceCollection, config: AppConfig
    ) -> None:
        """Register usage tracking services.

        Registers:
        - InMemoryUsageStore: Thread-safe storage with periodic persistence
        - UsageRecordingService: Service for recording usage metrics
        - StatisticsAggregationService: Service for aggregating statistics
        """
        try:
            from pathlib import Path

            from src.core.interfaces.statistics_service_interface import (
                IStatisticsService,
            )
            from src.core.interfaces.usage_recording_interface import (
                IUsageRecordingService,
            )
            from src.core.services.in_memory_usage_store import InMemoryUsageStore
            from src.core.services.statistics_aggregation_service import (
                StatisticsAggregationService,
            )
            from src.core.services.usage_recording_service import UsageRecordingService

            # Get usage tracking configuration
            usage_config = config.usage_tracking

            # Skip registration if usage tracking is disabled
            if not usage_config.enabled:
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Usage tracking is disabled")
                return

            # Register InMemoryUsageStore as singleton
            def usage_store_factory(provider: IServiceProvider) -> InMemoryUsageStore:
                cfg: AppConfig = provider.get_required_service(AppConfig)
                usage_cfg = cfg.usage_tracking
                return InMemoryUsageStore(
                    persistence_path=Path(usage_cfg.persistence_path),
                    flush_interval_seconds=usage_cfg.flush_interval_seconds,
                    max_records_in_memory=usage_cfg.max_records_in_memory,
                )

            services.add_singleton(
                InMemoryUsageStore, implementation_factory=usage_store_factory
            )

            # Register UsageRecordingService as singleton
            def usage_recording_factory(
                provider: IServiceProvider,
            ) -> UsageRecordingService:
                store: InMemoryUsageStore = provider.get_required_service(
                    InMemoryUsageStore
                )
                return UsageRecordingService(store)

            services.add_singleton(
                UsageRecordingService, implementation_factory=usage_recording_factory
            )
            services.add_singleton(
                IUsageRecordingService, implementation_factory=usage_recording_factory
            )

            # Register StatisticsAggregationService as singleton
            def statistics_service_factory(
                provider: IServiceProvider,
            ) -> StatisticsAggregationService:
                store: InMemoryUsageStore = provider.get_required_service(
                    InMemoryUsageStore
                )
                return StatisticsAggregationService(store)

            services.add_singleton(
                StatisticsAggregationService,
                implementation_factory=statistics_service_factory,
            )
            services.add_singleton(
                IStatisticsService, implementation_factory=statistics_service_factory
            )

            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Usage tracking services registered successfully "
                    f"(persistence_path={usage_config.persistence_path}, "
                    f"flush_interval={usage_config.flush_interval_seconds}s)"
                )

            # Register UsageTrackingEosSubscriber
            def usage_tracking_eos_subscriber_factory(
                provider: IServiceProvider,
            ) -> UsageTrackingEosSubscriber:
                """Factory to create UsageTrackingEosSubscriber."""
                from typing import cast

                from src.core.database.repositories.usage_repository import (
                    SessionMetricsRepository,
                )
                from src.core.interfaces.event_bus_interface import IEventBus
                from src.core.services.usage_tracking_eos_subscriber import (
                    UsageTrackingEosSubscriber,
                )

                event_bus: IEventBus = provider.get_required_service(
                    cast(type, IEventBus)
                )
                session_repo: SessionMetricsRepository = provider.get_required_service(
                    SessionMetricsRepository
                )
                return UsageTrackingEosSubscriber(
                    event_bus=event_bus, session_repository=session_repo
                )

            try:
                from src.core.services.usage_tracking_eos_subscriber import (
                    UsageTrackingEosSubscriber,
                )

                services.add_singleton(
                    UsageTrackingEosSubscriber,
                    implementation_factory=usage_tracking_eos_subscriber_factory,
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Registered UsageTrackingEosSubscriber")
            except ImportError:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "UsageTrackingEosSubscriber not available, skipping registration"
                    )
        except ImportError as e:
            logger.warning("Could not register usage tracking services: %s", e)

    def _register_usage_normalization_service(
        self, services: ServiceCollection
    ) -> None:
        """Register usage normalization service.

        Registers:
        - UsageCalculationService: Service for token calculation and derivation
        - UsageNormalizationService: Service for normalizing usage into canonical records
        """
        try:
            from typing import cast

            from src.core.interfaces.usage_normalization_service_interface import (
                IUsageNormalizationService,
            )
            from src.core.services.usage_calculation_service import (
                UsageCalculationService,
            )
            from src.core.services.usage_normalization_service import (
                UsageNormalizationService,
            )

            # Register UsageCalculationService as singleton
            def usage_calculation_factory(
                provider: IServiceProvider,
            ) -> UsageCalculationService:
                return UsageCalculationService()

            services.add_singleton(
                UsageCalculationService,
                implementation_factory=usage_calculation_factory,
            )

            # Register UsageNormalizationService as singleton
            def usage_normalization_factory(
                provider: IServiceProvider,
            ) -> UsageNormalizationService:
                calc_service: UsageCalculationService = provider.get_required_service(
                    UsageCalculationService
                )
                return UsageNormalizationService(calc_service)

            services.add_singleton(
                UsageNormalizationService,
                implementation_factory=usage_normalization_factory,
            )
            # Register interface binding that resolves to the concrete type
            services.add_singleton(
                cast(type, IUsageNormalizationService),
                implementation_factory=lambda p: p.get_required_service(
                    UsageNormalizationService
                ),
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered usage normalization service")
        except ImportError as e:
            logger.warning(
                "Could not register usage normalization service: %s",
                e,
                exc_info=True,
            )

    def _register_event_bus(self, services: ServiceCollection) -> None:
        """Register the event bus."""
        from typing import cast

        from src.core.interfaces.event_bus_interface import IEventBus
        from src.core.services.event_bus import EventBus

        def event_bus_factory(provider: IServiceProvider) -> EventBus:
            return EventBus()

        services.add_singleton(EventBus, implementation_factory=event_bus_factory)
        services.add_singleton(
            cast(type, IEventBus),
            implementation_factory=lambda p: p.get_required_service(EventBus),
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered EventBus")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that core services can be registered."""
        try:
            # Check that required modules are available

            # Validate config is not None  # type: ignore[unreachable]
            if config is None:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error("AppConfig is None")  # type: ignore[unreachable]
                return False

            return True
        except ImportError as e:  # type: ignore[misc]
            logger.error("Core services validation failed: %s", e)
            return False
