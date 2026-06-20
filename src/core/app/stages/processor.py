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
        if logger.isEnabledFor(logging.INFO):
            logger.info("Initializing processor services...")

        # Register command processor
        self._register_command_processor(services)

        # Register artifact service (request processor dependency)
        self._register_artifact_service(services)

        self._register_responses_session_store(services)
        self._register_responses_projectors(services)

        # Register command handler (request processor internal phase)
        self._register_command_handler(services)

        # Register backend preparer (request processor internal phase)
        self._register_backend_preparer(services)

        # Register session enricher (request processor dependency)
        self._register_session_enricher(services)

        # Register request side effects (request processor dependency)
        self._register_request_side_effects(services)

        # Register request transformation pipeline (request processor dependency)
        self._register_request_transform_pipeline(services)

        # Register backend executor (request processor internal phase)
        self._register_backend_executor(services)

        # Register backend processor
        self._register_backend_processor(services)

        # Register request processor
        self._register_request_processor(services)

        if logger.isEnabledFor(logging.INFO):
            logger.info("Processor services initialized successfully")

    def _register_command_processor(self, services: ServiceCollection) -> None:
        """Register command processor with command service dependency."""
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
            return CommandProcessor(command_service)  # DI-bypass-allowed

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

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered command processor")

    def _register_artifact_service(self, services: ServiceCollection) -> None:
        """Register artifact service for tool output preview management."""
        from src.core.services.artifact_service import ArtifactService

        # ArtifactService has no dependencies, register with factory
        services.add_singleton(
            ArtifactService,
            implementation_factory=lambda provider: ArtifactService(),
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered artifact service")

    def _register_responses_session_store(self, services: ServiceCollection) -> None:
        from src.core.interfaces.responses_session_store_interface import (
            IResponsesSessionStore,
        )
        from src.core.services.in_memory_responses_session_store import (
            InMemoryResponsesSessionStore,
        )

        def responses_session_store_factory(
            _provider: IServiceProvider,
        ) -> InMemoryResponsesSessionStore:
            return InMemoryResponsesSessionStore()

        services.add_singleton(
            InMemoryResponsesSessionStore,
            implementation_factory=responses_session_store_factory,
        )

        services.add_singleton_factory(
            cast(type, IResponsesSessionStore),
            implementation_factory=lambda provider: provider.get_required_service(
                InMemoryResponsesSessionStore
            ),
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered Responses session store")

    def _register_responses_projectors(self, services: ServiceCollection) -> None:
        from src.core.services.anthropic_responses_projector import (
            AnthropicResponsesProjector,
        )
        from src.core.services.gemini_responses_projector import (
            GeminiResponsesProjector,
        )
        from src.core.services.openai_responses_projector import (
            OpenAIResponsesProjector,
        )

        services.add_singleton(
            OpenAIResponsesProjector,
            implementation_factory=lambda _p: OpenAIResponsesProjector(),
        )
        services.add_singleton(
            AnthropicResponsesProjector,
            implementation_factory=lambda _p: AnthropicResponsesProjector(),
        )
        services.add_singleton(
            GeminiResponsesProjector,
            implementation_factory=lambda _p: GeminiResponsesProjector(),
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered Responses backend projectors")

    def _register_command_handler(self, services: ServiceCollection) -> None:
        """Register command handler (request processor internal phase)."""
        from src.core.interfaces.command_processor_interface import (
            ICommandProcessor,
        )
        from src.core.interfaces.request_processor_internal import ICommandHandler
        from src.core.interfaces.response_manager_interface import (
            IResponseManager,
        )
        from src.core.interfaces.session_manager_interface import (
            ISessionManager,
        )
        from src.core.services.artifact_service import ArtifactService
        from src.core.services.command_handler import CommandHandler

        def command_handler_factory(
            provider: IServiceProvider,
        ) -> CommandHandler:
            """Factory function for creating CommandHandler."""
            from typing import cast

            from src.core.interfaces.application_state_interface import (
                IApplicationState,
            )

            command_processor: ICommandProcessor = provider.get_required_service(
                cast(type, ICommandProcessor)
            )
            session_manager: ISessionManager = provider.get_required_service(
                cast(type, ISessionManager)
            )
            response_manager: IResponseManager = provider.get_required_service(
                cast(type, IResponseManager)
            )
            app_state: IApplicationState | None = provider.get_service(
                cast(type, IApplicationState)
            )
            artifact_service: ArtifactService | None = provider.get_service(
                ArtifactService
            )
            return CommandHandler(
                command_processor=command_processor,
                session_manager=session_manager,
                response_manager=response_manager,
                app_state=app_state,
                artifact_service=artifact_service,
            )

        # Register concrete implementation
        services.add_singleton(
            CommandHandler, implementation_factory=command_handler_factory
        )

        # Register interface binding that reuses the concrete singleton
        services.add_singleton_factory(
            cast(type, ICommandHandler),
            implementation_factory=lambda provider: provider.get_required_service(
                CommandHandler
            ),
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered command handler")

    def _register_backend_preparer(self, services: ServiceCollection) -> None:
        """Register backend preparer (request processor internal phase)."""
        from src.core.interfaces.backend_request_manager_interface import (
            IBackendRequestManager,
        )
        from src.core.interfaces.request_processor_internal import IBackendPreparer
        from src.core.services.backend_preparer import BackendPreparer

        def backend_preparer_factory(
            provider: IServiceProvider,
        ) -> BackendPreparer:
            """Factory function for creating BackendPreparer."""
            from typing import cast

            from src.core.interfaces.application_state_interface import (
                IApplicationState,
            )
            from src.core.services.model_catalog_service import ModelCatalogService

            backend_request_manager: IBackendRequestManager = (
                provider.get_required_service(cast(type, IBackendRequestManager))
            )
            app_state: IApplicationState | None = provider.get_service(
                cast(type, IApplicationState)
            )
            model_catalog: ModelCatalogService | None = provider.get_service(
                ModelCatalogService
            )
            return BackendPreparer(
                backend_request_manager=backend_request_manager,
                app_state=app_state,
                model_catalog=model_catalog,
            )

        # Register concrete implementation
        services.add_singleton(
            BackendPreparer, implementation_factory=backend_preparer_factory
        )

        # Register interface binding that reuses the concrete singleton
        services.add_singleton_factory(
            cast(type, IBackendPreparer),
            implementation_factory=lambda provider: provider.get_required_service(
                BackendPreparer
            ),
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered backend preparer")

    def _register_session_enricher(self, services: ServiceCollection) -> None:
        """Register session enricher (request processor internal phase)."""
        from src.core.interfaces.request_processor_internal import ISessionEnricher
        from src.core.interfaces.session_manager_interface import (
            ISessionManager,
        )
        from src.core.services.session_enricher import SessionEnricher

        def session_enricher_factory(
            provider: IServiceProvider,
        ) -> SessionEnricher:
            """Factory function for creating SessionEnricher."""
            from typing import cast

            from src.core.interfaces.application_state_interface import (
                IApplicationState,
            )

            session_manager: ISessionManager = provider.get_required_service(
                cast(type, ISessionManager)
            )
            app_state: IApplicationState | None = provider.get_service(
                cast(type, IApplicationState)
            )
            return SessionEnricher(session_manager=session_manager, app_state=app_state)

        # Register concrete implementation
        services.add_singleton(
            SessionEnricher, implementation_factory=session_enricher_factory
        )

        # Register interface binding that reuses the concrete singleton
        services.add_singleton_factory(
            cast(type, ISessionEnricher),
            implementation_factory=lambda provider: provider.get_required_service(
                SessionEnricher
            ),
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered session enricher")

    def _register_request_side_effects(self, services: ServiceCollection) -> None:
        """Register request side effects (request processor internal phase)."""
        from src.core.interfaces.request_processor_internal import (
            IRequestSideEffects,
        )
        from src.core.services.request_side_effects import RequestSideEffects

        def request_side_effects_factory(
            provider: IServiceProvider,
        ) -> RequestSideEffects:
            """Factory function for creating RequestSideEffects."""
            from src.core.memory.capture_middleware import MemoryCaptureMiddleware
            from src.core.memory.injection_middleware import (
                ContextInjectionMiddleware,
            )

            context_injector: ContextInjectionMiddleware | None = provider.get_service(
                ContextInjectionMiddleware
            )
            memory_capture: MemoryCaptureMiddleware | None = provider.get_service(
                MemoryCaptureMiddleware
            )
            return RequestSideEffects(
                context_injector=context_injector, memory_capture=memory_capture
            )

        # Register concrete implementation
        services.add_singleton(
            RequestSideEffects, implementation_factory=request_side_effects_factory
        )

        # Register interface binding that reuses the concrete singleton
        services.add_singleton_factory(
            cast(type, IRequestSideEffects),
            implementation_factory=lambda provider: provider.get_required_service(
                RequestSideEffects
            ),
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered request side effects")

    def _register_request_transform_pipeline(self, services: ServiceCollection) -> None:
        """Register request transformation pipeline."""
        from src.core.interfaces.application_state_interface import (
            IApplicationState,
        )
        from src.core.interfaces.request_processor_internal import (
            IRequestTransformPipeline,
        )
        from src.core.services.request_transform_pipeline import (
            RequestTransformPipeline,
        )

        def transform_pipeline_factory(
            provider: IServiceProvider,
        ) -> RequestTransformPipeline:
            """Factory function for creating RequestTransformPipeline."""

            app_state: IApplicationState | None = None
            try:
                app_state = provider.get_service(cast(type, IApplicationState))
            except ImportError as e:
                # Import errors: optional service not available
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "IApplicationState service not available: %s",
                        e,
                        exc_info=True,
                    )
            except AttributeError as e:
                # AttributeError: service method or type mismatch
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "IApplicationState service attribute error: %s",
                        e,
                        exc_info=True,
                    )
            except Exception as e:
                # Unexpected errors: log with full stack trace and continue with None
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Unexpected error resolving IApplicationState service: %s",
                        e,
                        exc_info=True,
                    )

            return RequestTransformPipeline(app_state=app_state)

        # Register interface binding
        services.add_singleton_factory(
            cast(type, IRequestTransformPipeline),
            implementation_factory=transform_pipeline_factory,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered request transformation pipeline")

    def _register_backend_executor(self, services: ServiceCollection) -> None:
        """Register backend executor (backend invocation and persistence side effects)."""
        from src.core.interfaces.backend_request_manager_interface import (
            IBackendRequestManager,
        )
        from src.core.interfaces.model_replacement_service_interface import (
            IModelReplacementService,
        )
        from src.core.interfaces.request_processor_internal import IBackendExecutor
        from src.core.interfaces.session_manager_interface import ISessionManager
        from src.core.services.backend_executor import BackendExecutor

        def backend_executor_factory(
            provider: IServiceProvider,
        ) -> IBackendExecutor:
            """Factory function for creating BackendExecutor."""
            backend_request_manager: IBackendRequestManager = (
                provider.get_required_service(cast(type, IBackendRequestManager))
            )
            session_manager: ISessionManager = provider.get_required_service(
                cast(type, ISessionManager)
            )
            replacement_service: IModelReplacementService | None = provider.get_service(
                cast(type, IModelReplacementService)
            )

            return BackendExecutor(
                backend_request_manager=backend_request_manager,
                session_manager=session_manager,
                replacement_service=replacement_service,
            )

        # Register interface binding
        services.add_singleton_factory(
            cast(type, IBackendExecutor),
            implementation_factory=backend_executor_factory,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered backend executor")

    def _register_backend_processor(self, services: ServiceCollection) -> None:
        """Register backend processor with backend and session service dependencies."""
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
            return BackendProcessor(  # DI-bypass-allowed
                backend_service, session_service, app_state
            )

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

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered backend processor")

    def _register_request_processor(self, services: ServiceCollection) -> None:
        """Register request processor as the main orchestrator."""
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
            backend_service: IBackendService = provider.get_required_service(
                cast(type, IBackendService)
            )
            session_service: ISessionService = provider.get_required_service(
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

        from src.core.interfaces.tool_progress_loop_guard_interface import (
            IToolProgressLoopGuard,
        )
        from src.core.services.tool_progress_loop_guard import ToolProgressLoopGuard

        def tool_progress_loop_guard_factory(
            provider: IServiceProvider,
        ) -> ToolProgressLoopGuard:
            app_config = provider.get_required_service(AppConfig)
            session_config = app_config.session
            return ToolProgressLoopGuard(
                max_consecutive_tool_followups=session_config.tool_progress_loop_max_consecutive_followups,
                max_repeated_tool_call_signature=session_config.tool_progress_loop_max_repeated_call_signature,
                max_repeated_tool_output=session_config.tool_progress_loop_max_repeated_output,
                max_counts_per_session=session_config.tool_progress_loop_max_counts_per_session,
                max_cached_sessions=session_config.tool_progress_loop_max_cached_sessions,
                enabled=session_config.tool_progress_loop_guard_enabled,
                action_mode=session_config.tool_progress_loop_action,
                steering_message=session_config.tool_progress_loop_steering_message,
            )

        services.add_singleton(
            ToolProgressLoopGuard,
            implementation_factory=tool_progress_loop_guard_factory,
        )
        services.add_singleton_factory(
            cast(type, IToolProgressLoopGuard),
            implementation_factory=lambda provider: provider.get_required_service(
                ToolProgressLoopGuard
            ),
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
            from src.core.interfaces.command_processor_interface import (
                ICommandProcessor,
            )
            from src.core.interfaces.response_manager_interface import (
                IResponseManager,
            )
            from src.core.interfaces.session_manager_interface import (
                ISessionManager,
            )
            from src.core.interfaces.tool_progress_loop_guard_interface import (
                IToolProgressLoopGuard,
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
            # project_dir_resolution_service removed from RequestProcessor constructor

            # Get internal phase handlers (optional for backwards compatibility)
            from src.core.interfaces.model_replacement_service_interface import (
                IModelReplacementService,
            )
            from src.core.interfaces.request_processor_internal import (
                IBackendExecutor,
                IBackendPreparer,
                ICommandHandler,
                IRequestSideEffects,
                IRequestTransformPipeline,
                ISessionEnricher,
            )

            command_handler: ICommandHandler = provider.get_required_service(
                cast(type, ICommandHandler)
            )
            backend_preparer: IBackendPreparer = provider.get_required_service(
                cast(type, IBackendPreparer)
            )
            session_enricher: ISessionEnricher = provider.get_required_service(
                cast(type, ISessionEnricher)
            )
            request_side_effects: IRequestSideEffects = provider.get_required_service(
                cast(type, IRequestSideEffects)
            )
            transform_pipeline: IRequestTransformPipeline = (
                provider.get_required_service(cast(type, IRequestTransformPipeline))
            )
            backend_executor: IBackendExecutor = provider.get_required_service(
                cast(type, IBackendExecutor)
            )
            replacement_service: IModelReplacementService | None = provider.get_service(
                cast(type, IModelReplacementService)
            )
            tool_progress_loop_guard: IToolProgressLoopGuard | None = (
                provider.get_service(cast(type, IToolProgressLoopGuard))
            )

            return RequestProcessor(  # DI-bypass-allowed
                command_processor,
                session_manager,
                backend_request_manager,
                response_manager,
                app_state=app_state,
                replacement_service=replacement_service,
                command_handler=command_handler,
                backend_preparer=backend_preparer,
                session_enricher=session_enricher,
                request_side_effects=request_side_effects,
                transform_pipeline=transform_pipeline,
                backend_executor=backend_executor,
                tool_progress_loop_guard=tool_progress_loop_guard,
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

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered request processor with all dependencies")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that processor services can be registered."""
        try:
            # Check that required modules are available

            return True
        except ImportError as e:  # type: ignore[misc]
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Processor services validation failed: %s", e, exc_info=True
                )
            return False
