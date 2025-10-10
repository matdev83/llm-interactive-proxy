"""
Processor services initialization stage.

This stage registers processor services that orchestrate the main
application logic:
- Command processor
- Backend processor
- Response processor
- Request processor
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.middleware_application_manager_interface import (
    IMiddlewareApplicationManager,
)
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import IResponseMiddleware

from .base import InitializationStage

logger = logging.getLogger(__name__)


class ProcessorStage(InitializationStage):
    """
    Stage for registering processor services.

    This stage registers:
    - Command processor (processes in-chat commands)
    - Backend processor (handles backend communication)
    - Response processor (processes responses with middleware)
    - Request processor (main request orchestrator)
    """

    @property
    def name(self) -> str:
        return "processors"

    def get_dependencies(self) -> list[str]:
        return ["backends", "commands"]

    def get_description(self) -> str:
        return "Register processor services (command, backend, response, request)"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register processor services."""
        logger.info("Initializing processor services...")

        # Register command processor
        self._register_command_processor(services)

        # Register backend processor
        self._register_backend_processor(services)

        # Register response processor
        self._register_response_processor(services)

        # Register request processor
        self._register_request_processor(services)

        logger.info("Processor services initialized successfully")

    def _register_command_processor(self, services: ServiceCollection) -> None:
        """Register command processor with command service dependency."""
        try:
            from src.core.interfaces.command_processor_interface import (
                ICommandProcessor,
            )
            from src.core.interfaces.command_service_interface import ICommandService
            from src.core.services.command_processor import CommandProcessor

            def command_processor_factory(
                provider: IServiceProvider,
            ) -> CommandProcessor:
                """Factory function for creating CommandProcessor."""
                from typing import cast

                command_service: ICommandService = provider.get_required_service(
                    cast(type, ICommandService)
                )
                return CommandProcessor(
                    command_service
                )  # No change needed here, constructor is correct

            # Register concrete implementation
            services.add_singleton(
                CommandProcessor, implementation_factory=command_processor_factory
            )

            # Register interface binding that reuses the concrete singleton
            from typing import cast

            services.add_singleton_factory(
                cast(type, ICommandProcessor),
                implementation_factory=lambda provider: provider.get_required_service(
                    CommandProcessor
                ),
            )

            logger.debug("Registered command processor")
        except ImportError as e:  # type: ignore[misc]
            logger.warning(f"Could not register command processor: {e}")

    def _register_backend_processor(self, services: ServiceCollection) -> None:
        """Register backend processor with backend and session service dependencies."""
        try:
            from src.core.interfaces.backend_processor_interface import (
                IBackendProcessor,
            )
            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.interfaces.session_service_interface import ISessionService
            from src.core.services.backend_processor import BackendProcessor

            def backend_processor_factory(
                provider: IServiceProvider,
            ) -> BackendProcessor:
                """Factory function for creating BackendProcessor."""
                from typing import cast

                backend_service: IBackendService = provider.get_required_service(
                    cast(type, IBackendService)
                )
                session_service: ISessionService = provider.get_required_service(
                    cast(type, ISessionService)
                )
                # Resolve application state for failover routes and settings
                from src.core.interfaces.application_state_interface import (
                    IApplicationState,
                )

                app_state: IApplicationState = provider.get_required_service(
                    cast(type, IApplicationState)
                )
                return BackendProcessor(backend_service, session_service, app_state)

            # Register concrete implementation
            services.add_singleton(
                BackendProcessor, implementation_factory=backend_processor_factory
            )

            # Register interface binding that reuses the concrete singleton
            services.add_singleton_factory(
                cast(type, IBackendProcessor),
                implementation_factory=lambda provider: provider.get_required_service(
                    BackendProcessor
                ),
            )

            logger.debug("Registered backend processor")
        except ImportError as e:  # type: ignore[misc]
            logger.warning(f"Could not register backend processor: {e}")

    def _register_response_processor(self, services: ServiceCollection) -> None:
        """Register response processor with middleware, loop detector, and streaming pipeline."""
        try:
            from src.core.interfaces.application_state_interface import (
                IApplicationState,
            )
            from src.core.interfaces.loop_detector_interface import ILoopDetector
            from src.core.interfaces.response_processor_interface import (
                IResponseProcessor,
            )
            from src.core.interfaces.streaming_response_processor_interface import (
                IStreamNormalizer,
            )
            from src.core.services.response_processor_service import ResponseProcessor

            def response_processor_factory(
                provider: IServiceProvider,
            ) -> ResponseProcessor:
                """Factory function for creating ResponseProcessor with middleware and streaming pipeline."""
                app_state: IApplicationState = provider.get_required_service(
                    cast(type, IApplicationState)
                )
                loop_detector: ILoopDetector | None = provider.get_service(
                    cast(type, ILoopDetector)
                )

                middleware: list[IResponseMiddleware] = []
                if loop_detector:
                    try:
                        from src.core.services.response_middleware import (
                            LoopDetectionMiddleware,
                        )

                        # Instantiate LoopDetectionMiddleware with the resolved ILoopDetector
                        middleware.append(
                            LoopDetectionMiddleware(loop_detector, priority=10)
                        )
                        logger.debug("Added loop detection middleware")
                    except ImportError:
                        logger.warning("Loop detection middleware not available")

                # Always resolve stream normalizer since it's needed for loop detection
                stream_normalizer: IStreamNormalizer = provider.get_required_service(
                    cast(type, IStreamNormalizer)
                )
                logger.debug("Resolved StreamNormalizer for ResponseProcessor")

                response_parser: IResponseParser = provider.get_required_service(
                    cast(type, IResponseParser)
                )
                middleware_application_manager: IMiddlewareApplicationManager = (
                    provider.get_required_service(
                        cast(type, IMiddlewareApplicationManager)
                    )
                )

                return ResponseProcessor(
                    app_state=app_state,
                    response_parser=response_parser,
                    middleware_application_manager=middleware_application_manager,
                    stream_normalizer=stream_normalizer,
                )

            services.add_singleton(
                ResponseProcessor, implementation_factory=response_processor_factory
            )
            services.add_singleton_factory(
                cast(type, IResponseProcessor),
                implementation_factory=lambda provider: provider.get_required_service(
                    ResponseProcessor
                ),
            )

            logger.debug(
                "Registered response processor with middleware and optional streaming pipeline"
            )
        except ImportError as e:
            logger.warning(f"Could not register response processor: {e}")

    def _register_request_processor(self, services: ServiceCollection) -> None:
        """Register request processor as the main orchestrator."""
        try:
            from src.core.interfaces.command_processor_interface import (
                ICommandProcessor,
            )
            from src.core.interfaces.request_processor_interface import (
                IRequestProcessor,
            )
            from src.core.services.project_directory_resolution_service import (
                ProjectDirectoryResolutionService,
            )
            from src.core.services.request_processor_service import RequestProcessor

            project_dir_service_cls = ProjectDirectoryResolutionService

            from src.core.interfaces.backend_service_interface import IBackendService
            from src.core.interfaces.session_service_interface import ISessionService

            def project_dir_service_factory(
                provider: IServiceProvider,
            ) -> ProjectDirectoryResolutionService:
                from typing import cast

                app_config = provider.get_required_service(AppConfig)
                backend_service = provider.get_required_service(
                    cast(type, IBackendService)
                )
                session_service = provider.get_required_service(
                    cast(type, ISessionService)
                )
                return project_dir_service_cls(
                    app_config,
                    backend_service,
                    session_service,
                )

            services.add_singleton(
                ProjectDirectoryResolutionService,
                implementation_factory=project_dir_service_factory,
            )

            def request_processor_factory(
                provider: IServiceProvider,
            ) -> RequestProcessor:
                """Factory function for creating RequestProcessor with decomposed services."""
                from typing import cast

                from src.core.interfaces.application_state_interface import (
                    IApplicationState,
                )
                from src.core.interfaces.backend_request_manager_interface import (
                    IBackendRequestManager,
                )
                from src.core.interfaces.response_manager_interface import (
                    IResponseManager,
                )
                from src.core.interfaces.session_manager_interface import (
                    ISessionManager,
                )

                command_processor: ICommandProcessor = provider.get_required_service(
                    cast(type, ICommandProcessor)
                )
                session_manager: ISessionManager = provider.get_required_service(
                    cast(type, ISessionManager)
                )
                backend_request_manager: IBackendRequestManager = (
                    provider.get_required_service(cast(type, IBackendRequestManager))
                )
                response_manager: IResponseManager = provider.get_required_service(
                    cast(type, IResponseManager)
                )
                app_state: IApplicationState | None = provider.get_service(
                    cast(type, IApplicationState)
                )
                project_dir_resolution_service: (
                    ProjectDirectoryResolutionService | None
                ) = provider.get_service(ProjectDirectoryResolutionService)

                return RequestProcessor(
                    command_processor,
                    session_manager,
                    backend_request_manager,
                    response_manager,
                    app_state=app_state,
                    project_dir_resolution_service=project_dir_resolution_service,
                )

            # Register concrete implementation
            services.add_singleton(
                RequestProcessor, implementation_factory=request_processor_factory
            )

            # Register interface binding that reuses the concrete singleton
            services.add_singleton_factory(
                cast(type, IRequestProcessor),
                implementation_factory=lambda provider: provider.get_required_service(
                    RequestProcessor
                ),
            )

            logger.debug("Registered request processor with all dependencies")
        except ImportError as e:  # type: ignore[misc]
            logger.warning(f"Could not register request processor: {e}")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that processor services can be registered."""
        try:
            # Check that required modules are available

            return True
        except ImportError as e:  # type: ignore[misc]
            logger.error(f"Processor services validation failed: {e}")
            return False
