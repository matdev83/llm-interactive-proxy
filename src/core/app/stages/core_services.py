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
from src.core.interfaces.streaming_response_processor_interface import IStreamNormalizer

# from src.core.interfaces.secure_state_interface import ISecureStateService # Removed unresolved import
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
            stream_normalizer: IStreamNormalizer = provider.get_required_service(
                IStreamNormalizer  # type: ignore[type-abstract]
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
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register session repository: {e}")

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
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register session service: {e}")

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
                logger.error(f"Failed to register core services from DI module: {e}")
            raise

        # Register wire capture service
        self._register_wire_capture_service(services)

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
                    if logger.isEnabledFor(logging.INFO):
                        logger.info(f"Using CBOR wire capture: {cbor_capture_dir}")
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
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register wire capture service: {e}")

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
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Core services validation failed: {e}")
            return False
