"""
Core request processing registration helper.

Registers:
- Request processing orchestration (RequestProcessor, BackendProcessor, BackendRequestManager)
- Phase components (SessionEnricher, RequestSideEffects, CommandHandler, BackendPreparer, RequestTransformPipeline, BackendExecutor)
"""

from __future__ import annotations

import contextlib
import logging
from typing import cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import (
    register_singleton_if_absent,
)
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_request_processing_orchestration(services: ServiceCollection) -> None:
    """Register request processing orchestration services."""
    from src.core.interfaces.backend_processor_interface import IBackendProcessor
    from src.core.interfaces.backend_request_manager_interface import (
        IBackendRequestManager,
    )
    from src.core.interfaces.backend_service_interface import IBackendService
    from src.core.interfaces.request_processor_interface import IRequestProcessor
    from src.core.interfaces.response_handler_interface import (
        INonStreamingResponseHandler,
        IStreamingResponseHandler,
    )
    from src.core.interfaces.response_manager_interface import IResponseManager
    from src.core.interfaces.response_processor_interface import IResponseProcessor
    from src.core.interfaces.session_service_interface import ISessionService
    from src.core.services.backend_processor import BackendProcessor
    from src.core.services.backend_request_manager_service import BackendRequestManager
    from src.core.services.request_processor_service import RequestProcessor
    from src.core.services.response_handlers import (
        DefaultNonStreamingResponseHandler,
        DefaultStreamingResponseHandler,
    )

    # Register response handlers
    register_singleton_if_absent(services, DefaultNonStreamingResponseHandler)
    register_singleton_if_absent(services, DefaultStreamingResponseHandler)
    try:
        register_singleton_if_absent(
            services,
            cast(type, INonStreamingResponseHandler),
            implementation_type=DefaultNonStreamingResponseHandler,  # type: ignore[type-abstract]
        )
        register_singleton_if_absent(
            services,
            cast(type, IStreamingResponseHandler),
            implementation_type=DefaultStreamingResponseHandler,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register response handler interfaces: {e}")

    # Register BackendProcessor
    def _backend_processor_factory(provider: IServiceProvider) -> BackendProcessor:
        from src.core.interfaces.application_state_interface import IApplicationState
        from src.core.interfaces.session_service_interface import ISessionService

        backend_service: IBackendService = provider.get_required_service(
            cast(type, IBackendService)
        )
        session_service: ISessionService = provider.get_required_service(
            cast(type, ISessionService)
        )
        app_state: IApplicationState = provider.get_required_service(
            cast(type, IApplicationState)
        )
        return BackendProcessor(backend_service, session_service, app_state)

    register_singleton_if_absent(
        services, BackendProcessor, implementation_factory=_backend_processor_factory
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, IBackendProcessor),
            implementation_factory=_backend_processor_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IBackendProcessor interface: {e}")

    # Register AgentResponseFormatter and ResponseManager
    from src.core.interfaces.agent_response_formatter_interface import (
        IAgentResponseFormatter,
    )
    from src.core.services.response_manager_service import (
        AgentResponseFormatter,
        ResponseManager,
    )
    from src.core.services.session_service_impl import SessionService

    def _agent_response_formatter_factory(
        provider: IServiceProvider,
    ) -> AgentResponseFormatter:
        session_service = provider.get_service(SessionService)
        return AgentResponseFormatter(session_service=session_service)

    register_singleton_if_absent(
        services,
        AgentResponseFormatter,
        implementation_factory=_agent_response_formatter_factory,
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, IAgentResponseFormatter),
            implementation_factory=_agent_response_formatter_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IAgentResponseFormatter interface: {e}")

    def _response_manager_factory(provider: IServiceProvider) -> ResponseManager:
        agent_response_formatter = provider.get_required_service(
            cast(type[IAgentResponseFormatter], IAgentResponseFormatter)
        )
        session_service = provider.get_required_service(
            cast(type[ISessionService], ISessionService)
        )
        return ResponseManager(agent_response_formatter, session_service)

    register_singleton_if_absent(
        services, ResponseManager, implementation_factory=_response_manager_factory
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, IResponseManager),
            implementation_factory=_response_manager_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IResponseManager interface: {e}")

    # Register ResponseProcessor
    from src.core.interfaces.response_parser_interface import IResponseParser
    from src.core.interfaces.streaming_response_processor_interface import (
        IStreamNormalizer,
    )
    from src.core.memory.capture_middleware import MemoryCaptureMiddleware
    from src.core.services.response_processor_service import ResponseProcessor

    def _real_response_processor_factory(
        provider: IServiceProvider,
    ) -> ResponseProcessor:
        from src.core.interfaces.application_state_interface import IApplicationState

        response_parser: IResponseParser = provider.get_required_service(
            cast(type, IResponseParser)
        )
        app_state = provider.get_service(cast(type, IApplicationState))  # type: ignore[type-abstract]
        # Resolve IStreamNormalizer from DI (registered by streaming registrar)
        stream_normalizer = provider.get_required_service(
            cast(type[IStreamNormalizer], IStreamNormalizer)
        )
        memory_capture = provider.get_service(MemoryCaptureMiddleware)
        return ResponseProcessor(
            response_parser=response_parser,
            app_state=app_state,
            stream_normalizer=stream_normalizer,
            memory_capture=memory_capture,
        )

    register_singleton_if_absent(
        services,
        ResponseProcessor,
        implementation_factory=_real_response_processor_factory,
    )
    register_singleton_if_absent(
        services,
        cast(type, IResponseProcessor),
        implementation_factory=_real_response_processor_factory,  # type: ignore[type-abstract]
    )

    # Register BackendRequestManager
    def _backend_request_manager_factory(
        provider: IServiceProvider,
    ) -> BackendRequestManager:
        from src.core.interfaces.angel_service_interface import IAngelServiceFactory
        from src.core.interfaces.wire_capture_interface import IWireCapture
        from src.core.services.history_compaction_service import (
            HistoryCompactionService,
        )
        from src.core.services.request_deduplication_service import (
            RequestDeduplicationService,
        )

        backend_processor = provider.get_required_service(
            cast(type[IBackendProcessor], IBackendProcessor)
        )
        response_processor = provider.get_required_service(
            cast(type[IResponseProcessor], IResponseProcessor)
        )

        # IAngelServiceFactory and IWireCapture are optional - create mocks if not available
        angel_service_factory = provider.get_service(cast(type, IAngelServiceFactory))  # type: ignore[type-abstract]
        if angel_service_factory is None:
            from unittest.mock import MagicMock

            angel_service_factory = MagicMock(spec=IAngelServiceFactory)

        wire_capture = provider.get_service(cast(type, IWireCapture))  # type: ignore[type-abstract]

        history_compaction_service = provider.get_service(HistoryCompactionService)
        config = provider.get_required_service(AppConfig)

        # Request deduplication service (configurable via config.request_dedup_window)
        dedup_window = getattr(config, "request_dedup_window", 3.0)
        dedup_max_cache = getattr(config, "request_dedup_max_cache", 10000)
        dedup_enabled = dedup_window > 0
        dedup_service: RequestDeduplicationService | None = None
        if dedup_enabled:
            dedup_service = RequestDeduplicationService(
                window_seconds=dedup_window,
                enabled=True,
                max_cache_size=dedup_max_cache,
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Request deduplication enabled with window=%.1fs, max_cache=%d",
                    dedup_window,
                    dedup_max_cache,
                )

        return BackendRequestManager(
            backend_processor,
            response_processor,
            angel_service_factory,
            wire_capture,
            history_compaction_service=history_compaction_service,
            config=config,
            dedup_service=dedup_service,
        )

    register_singleton_if_absent(
        services,
        BackendRequestManager,
        implementation_factory=_backend_request_manager_factory,
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, IBackendRequestManager),
            implementation_factory=_backend_request_manager_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IBackendRequestManager interface: {e}")

    # Register LoopDetector
    from src.core.interfaces.loop_detector_interface import ILoopDetector
    from src.loop_detection.hybrid_detector import HybridLoopDetector

    def _loop_detector_factory(provider: IServiceProvider) -> ILoopDetector:
        config = provider.get_service(AppConfig)
        if (
            config
            and hasattr(config, "session")
            and hasattr(config.session, "loop_detection")
        ):
            loop_config = config.session.loop_detection
            if not loop_config or not loop_config.get("enabled", True):
                from src.loop_detection.detector import NoOpLoopDetector

                return NoOpLoopDetector()
        from src.loop_detection.config import (
            InternalLoopDetectionConfig,
            PatternThresholds,
        )

        internal_config = InternalLoopDetectionConfig()
        long_threshold = internal_config.long_pattern_threshold or PatternThresholds(
            min_repetitions=3,
            min_total_length=300,
        )
        short_config = {
            "content_loop_threshold": internal_config.content_loop_threshold,
            "content_chunk_size": internal_config.content_chunk_size,
            "max_history_length": internal_config.max_history_length,
        }
        long_config = {
            "min_pattern_length": long_threshold.min_total_length,
            "max_pattern_length": internal_config.max_pattern_length,
            "min_repetitions": long_threshold.min_repetitions,
            "max_history": internal_config.max_history_length,
        }

        return HybridLoopDetector(
            short_detector_config=short_config,
            long_detector_config=long_config,
        )

    register_singleton_if_absent(
        services, HybridLoopDetector, implementation_factory=_loop_detector_factory
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, ILoopDetector),
            implementation_factory=_loop_detector_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register ILoopDetector interface: {e}")

    # Register RequestProcessor
    def _response_processor_factory(provider: IServiceProvider) -> RequestProcessor:
        from src.core.interfaces.application_state_interface import IApplicationState
        from src.core.interfaces.backend_request_manager_interface import (
            IBackendRequestManager,
        )
        from src.core.interfaces.command_processor_interface import ICommandProcessor
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
        from src.core.interfaces.response_manager_interface import IResponseManager
        from src.core.interfaces.session_manager_interface import ISessionManager

        command_processor: ICommandProcessor = provider.get_required_service(
            cast(type, ICommandProcessor)
        )
        session_manager: ISessionManager = provider.get_required_service(
            cast(type, ISessionManager)
        )
        backend_request_manager: IBackendRequestManager = provider.get_required_service(
            cast(type, IBackendRequestManager)
        )
        response_manager: IResponseManager = provider.get_required_service(
            cast(type, IResponseManager)
        )
        app_state: IApplicationState = provider.get_required_service(
            cast(type, IApplicationState)
        )
        replacement_service = provider.get_service(cast(type, IModelReplacementService))
        session_enricher: ISessionEnricher = provider.get_required_service(
            cast(type, ISessionEnricher)
        )
        request_side_effects: IRequestSideEffects = provider.get_required_service(
            cast(type, IRequestSideEffects)
        )
        command_handler: ICommandHandler = provider.get_required_service(
            cast(type, ICommandHandler)
        )
        backend_preparer: IBackendPreparer = provider.get_required_service(
            cast(type, IBackendPreparer)
        )
        transform_pipeline: IRequestTransformPipeline = provider.get_required_service(
            cast(type, IRequestTransformPipeline)
        )
        backend_executor: IBackendExecutor = provider.get_required_service(
            cast(type, IBackendExecutor)
        )

        return RequestProcessor(
            command_processor=command_processor,
            session_manager=session_manager,
            backend_request_manager=backend_request_manager,
            response_manager=response_manager,
            session_enricher=session_enricher,
            request_side_effects=request_side_effects,
            command_handler=command_handler,
            backend_preparer=backend_preparer,
            transform_pipeline=transform_pipeline,
            backend_executor=backend_executor,
            app_state=app_state,
            replacement_service=replacement_service,
        )

    register_singleton_if_absent(
        services, RequestProcessor, implementation_factory=_response_processor_factory
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, IRequestProcessor),
            implementation_factory=_response_processor_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IRequestProcessor interface: {e}")


def register_phase_components(services: ServiceCollection) -> None:
    """Register request processor phase components."""
    from src.core.interfaces.request_processor_internal import (
        IBackendExecutor,
        IBackendPreparer,
        ICommandHandler,
        IRequestSideEffects,
        IRequestTransformPipeline,
        ISessionEnricher,
    )
    from src.core.services.artifact_service import ArtifactService
    from src.core.services.backend_executor import BackendExecutor
    from src.core.services.backend_preparer import BackendPreparer
    from src.core.services.command_handler import CommandHandler
    from src.core.services.request_side_effects import RequestSideEffects
    from src.core.services.request_transform_pipeline import RequestTransformPipeline
    from src.core.services.session_enricher import SessionEnricher

    # Register ArtifactService
    register_singleton_if_absent(
        services,
        ArtifactService,
        implementation_factory=lambda provider: ArtifactService(),
    )

    # Register CommandHandler
    def _command_handler_factory(provider: IServiceProvider) -> CommandHandler:
        from src.core.interfaces.application_state_interface import IApplicationState
        from src.core.interfaces.command_processor_interface import (
            ICommandProcessor,
        )
        from src.core.interfaces.response_manager_interface import IResponseManager
        from src.core.interfaces.session_manager_interface import ISessionManager

        command_processor: ICommandProcessor = provider.get_required_service(
            cast(type, ICommandProcessor)
        )
        session_manager: ISessionManager = provider.get_required_service(
            cast(type, ISessionManager)
        )
        response_manager: IResponseManager = provider.get_required_service(
            cast(type, IResponseManager)
        )
        app_state = provider.get_service(cast(type, IApplicationState))
        artifact_service = provider.get_service(ArtifactService)
        return CommandHandler(
            command_processor=command_processor,
            session_manager=session_manager,
            response_manager=response_manager,
            app_state=app_state,
            artifact_service=artifact_service,
        )

    register_singleton_if_absent(
        services, CommandHandler, implementation_factory=_command_handler_factory
    )
    register_singleton_if_absent(
        services,
        cast(type, ICommandHandler),
        implementation_factory=lambda provider: provider.get_required_service(
            CommandHandler
        ),  # type: ignore[type-abstract]
    )

    # Register BackendPreparer
    def _backend_preparer_factory(provider: IServiceProvider) -> BackendPreparer:
        from src.core.interfaces.application_state_interface import IApplicationState
        from src.core.interfaces.backend_request_manager_interface import (
            IBackendRequestManager,
        )

        backend_request_manager: IBackendRequestManager = provider.get_required_service(
            cast(type, IBackendRequestManager)
        )
        app_state = provider.get_service(cast(type, IApplicationState))
        return BackendPreparer(
            backend_request_manager=backend_request_manager, app_state=app_state
        )

    register_singleton_if_absent(
        services, BackendPreparer, implementation_factory=_backend_preparer_factory
    )
    register_singleton_if_absent(
        services,
        cast(type, IBackendPreparer),
        implementation_factory=lambda provider: provider.get_required_service(
            BackendPreparer
        ),  # type: ignore[type-abstract]
    )

    # Register SessionEnricher
    def _session_enricher_factory(provider: IServiceProvider) -> SessionEnricher:
        from src.core.interfaces.application_state_interface import IApplicationState
        from src.core.interfaces.session_manager_interface import ISessionManager

        session_manager: ISessionManager = provider.get_required_service(
            cast(type, ISessionManager)
        )
        app_state = provider.get_service(cast(type, IApplicationState))
        return SessionEnricher(session_manager=session_manager, app_state=app_state)

    register_singleton_if_absent(
        services, SessionEnricher, implementation_factory=_session_enricher_factory
    )
    register_singleton_if_absent(
        services,
        cast(type, ISessionEnricher),
        implementation_factory=lambda provider: provider.get_required_service(
            SessionEnricher
        ),  # type: ignore[type-abstract]
    )

    # Register RequestSideEffects
    def _request_side_effects_factory(
        provider: IServiceProvider,
    ) -> RequestSideEffects:
        from src.core.memory.capture_middleware import MemoryCaptureMiddleware
        from src.core.memory.injection_middleware import (
            ContextInjectionMiddleware,
        )

        context_injector = provider.get_service(ContextInjectionMiddleware)
        memory_capture = provider.get_service(MemoryCaptureMiddleware)
        return RequestSideEffects(
            context_injector=context_injector, memory_capture=memory_capture
        )

    register_singleton_if_absent(
        services,
        RequestSideEffects,
        implementation_factory=_request_side_effects_factory,
    )
    register_singleton_if_absent(
        services,
        cast(type, IRequestSideEffects),
        implementation_factory=lambda provider: provider.get_required_service(
            RequestSideEffects
        ),  # type: ignore[type-abstract]
    )

    # Register RequestTransformPipeline
    def _transform_pipeline_factory(
        provider: IServiceProvider,
    ) -> RequestTransformPipeline:
        from src.core.interfaces.application_state_interface import IApplicationState

        app_state = None
        with contextlib.suppress(Exception):
            app_state = provider.get_service(cast(type, IApplicationState))
        return RequestTransformPipeline(app_state=app_state)

    register_singleton_if_absent(
        services,
        cast(type, IRequestTransformPipeline),
        implementation_factory=_transform_pipeline_factory,  # type: ignore[type-abstract]
    )

    # Register BackendExecutor
    def _backend_executor_factory(provider: IServiceProvider) -> IBackendExecutor:
        from src.core.interfaces.backend_request_manager_interface import (
            IBackendRequestManager,
        )
        from src.core.interfaces.model_replacement_service_interface import (
            IModelReplacementService,
        )
        from src.core.interfaces.session_manager_interface import ISessionManager

        backend_request_manager: IBackendRequestManager = provider.get_required_service(
            cast(type, IBackendRequestManager)
        )
        session_manager: ISessionManager = provider.get_required_service(
            cast(type, ISessionManager)
        )
        replacement_service = provider.get_service(cast(type, IModelReplacementService))
        return BackendExecutor(
            backend_request_manager=backend_request_manager,
            session_manager=session_manager,
            replacement_service=replacement_service,
        )

    register_singleton_if_absent(
        services,
        cast(type, IBackendExecutor),
        implementation_factory=_backend_executor_factory,  # type: ignore[type-abstract]
    )
