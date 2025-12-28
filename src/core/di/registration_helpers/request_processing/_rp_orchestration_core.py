"""
Core request processing orchestration registrations.

Registers:
- Response handlers (non-streaming, streaming)
- BackendProcessor / IBackendProcessor
- AgentResponseFormatter / IAgentResponseFormatter
- ResponseManager / IResponseManager
- AngelServiceFactory / IAngelServiceFactory
- ResponseProcessor / IResponseProcessor
- BackendRequestManager / IBackendRequestManager
- RequestProcessor / IRequestProcessor
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider

if TYPE_CHECKING:
    from src.core.services.request_deduplication_service import (
        RequestDeduplicationService,
    )

logger = logging.getLogger(__name__)


def register_orchestration_core_services(services: ServiceCollection) -> None:
    """Register core orchestration services."""
    _register_response_handlers(services)
    _register_backend_processor(services)
    _register_response_manager(services)
    _register_angel_service_factory(services)
    _register_response_processor(services)
    _register_backend_request_manager(services)
    _register_request_processor(services)


def _register_response_handlers(services: ServiceCollection) -> None:
    """Register non-streaming and streaming response handlers."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.response_handler_interface import (
        INonStreamingResponseHandler,
        IStreamingResponseHandler,
    )
    from src.core.services.response_handlers import (
        DefaultNonStreamingResponseHandler,
        DefaultStreamingResponseHandler,
    )

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


def _register_backend_processor(services: ServiceCollection) -> None:
    """Register BackendProcessor and IBackendProcessor."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.backend_processor_interface import IBackendProcessor
    from src.core.interfaces.backend_service_interface import IBackendService
    from src.core.interfaces.session_service_interface import ISessionService
    from src.core.services.backend_processor import BackendProcessor

    def _backend_processor_factory(provider: IServiceProvider) -> BackendProcessor:
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


def _register_response_manager(services: ServiceCollection) -> None:
    """Register AgentResponseFormatter and ResponseManager."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.agent_response_formatter_interface import (
        IAgentResponseFormatter,
    )
    from src.core.interfaces.response_manager_interface import IResponseManager
    from src.core.interfaces.session_service_interface import ISessionService
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
            IAgentResponseFormatter,
            implementation_factory=_agent_response_formatter_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IAgentResponseFormatter interface: {e}")

    def _response_manager_factory(provider: IServiceProvider) -> ResponseManager:
        agent_response_formatter: (
            IAgentResponseFormatter
        ) = provider.get_required_service(
            cast(type, IAgentResponseFormatter)  # type: ignore[type-abstract]
        )
        session_service: ISessionService = provider.get_required_service(
            cast(type, ISessionService)  # type: ignore[type-abstract]
        )
        return ResponseManager(agent_response_formatter, session_service)

    register_singleton_if_absent(
        services, ResponseManager, implementation_factory=_response_manager_factory
    )
    try:
        register_singleton_if_absent(
            services,
            IResponseManager,
            implementation_factory=_response_manager_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IResponseManager interface: {e}")


def _register_angel_service_factory(services: ServiceCollection) -> None:
    """Register AngelServiceFactory (optional feature)."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.angel_service_interface import IAngelServiceFactory
    from src.core.services.angel_service_factory import DefaultAngelServiceFactory

    register_singleton_if_absent(services, DefaultAngelServiceFactory)
    try:
        register_singleton_if_absent(
            services,
            cast(type, IAngelServiceFactory),
            implementation_type=DefaultAngelServiceFactory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register IAngelServiceFactory interface: {e}")


def _register_response_processor(services: ServiceCollection) -> None:
    """Register ResponseProcessor and IResponseProcessor."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.response_parser_interface import IResponseParser
    from src.core.interfaces.response_processor_interface import (
        IResponseProcessor,
    )
    from src.core.interfaces.session_cancellation_coordinator_interface import (
        ISessionCancellationCoordinator,
    )
    from src.core.interfaces.streaming_response_processor_interface import (
        IStreamNormalizer,
    )
    from src.core.memory.capture_middleware import MemoryCaptureMiddleware
    from src.core.services.response_processor_service import ResponseProcessor

    def _real_response_processor_factory(
        provider: IServiceProvider,
    ) -> ResponseProcessor:
        response_parser: IResponseParser = provider.get_required_service(
            cast(type, IResponseParser)  # type: ignore[type-abstract]
        )
        app_state = provider.get_service(cast(type, IApplicationState))  # type: ignore[type-abstract]
        # Resolve IStreamNormalizer from DI (registered by streaming registrar)
        stream_normalizer: IStreamNormalizer = provider.get_required_service(
            cast(type, IStreamNormalizer)  # type: ignore[type-abstract]
        )
        memory_capture = provider.get_service(MemoryCaptureMiddleware)
        cancellation_coordinator = provider.get_service(
            cast(type, ISessionCancellationCoordinator)  # type: ignore[type-abstract]
        )
        return ResponseProcessor(
            response_parser=response_parser,
            app_state=app_state,
            stream_normalizer=stream_normalizer,
            memory_capture=memory_capture,
            cancellation_coordinator=cancellation_coordinator,
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


def _create_deduplication_service(
    provider: IServiceProvider, config: AppConfig
) -> RequestDeduplicationService | None:
    """Extract dedup service creation logic.

    Returns:
        RequestDeduplicationService if enabled, None otherwise.
    """
    from src.core.services.request_deduplication_service import (
        RequestDeduplicationService,
    )

    dedup_window = getattr(config, "request_dedup_window", 3.0)
    dedup_max_cache = getattr(config, "request_dedup_max_cache", 10000)

    if dedup_window <= 0:
        return None

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Request deduplication enabled with window=%.1fs, max_cache=%d",
            dedup_window,
            dedup_max_cache,
        )

    return RequestDeduplicationService(
        window_seconds=dedup_window,
        enabled=True,
        max_cache_size=dedup_max_cache,
    )


def _register_backend_request_manager(services: ServiceCollection) -> None:
    """Register BackendRequestManager and IBackendRequestManager."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.angel_service_interface import IAngelServiceFactory
    from src.core.interfaces.backend_processor_interface import IBackendProcessor
    from src.core.interfaces.backend_request_manager_components import (
        IBackendRequestPreparation,
        INonStreamingBackendResponseHandler,
        IStreamingBackendResponseHandler,
    )
    from src.core.interfaces.backend_request_manager_interface import (
        IBackendRequestManager,
    )
    from src.core.interfaces.response_processor_interface import IResponseProcessor
    from src.core.interfaces.wire_capture_interface import IWireCapture
    from src.core.services.backend_request_manager_service import BackendRequestManager

    def _backend_request_manager_factory(
        provider: IServiceProvider,
    ) -> BackendRequestManager:
        from src.core.services.history_compaction_service import (
            HistoryCompactionService,
        )

        backend_processor: IBackendProcessor = provider.get_required_service(
            cast(type, IBackendProcessor)  # type: ignore[type-abstract]
        )
        response_processor: IResponseProcessor = provider.get_required_service(
            cast(type, IResponseProcessor)  # type: ignore[type-abstract]
        )

        # IAngelServiceFactory and IWireCapture are optional - create mocks if not available
        angel_service_factory = provider.get_service(cast(type, IAngelServiceFactory))  # type: ignore[type-abstract]
        if angel_service_factory is None:
            from unittest.mock import MagicMock

            angel_service_factory = MagicMock(spec=IAngelServiceFactory)

        wire_capture = provider.get_service(cast(type, IWireCapture))  # type: ignore[type-abstract]

        # Resolve component dependencies
        request_preparation: IBackendRequestPreparation = provider.get_required_service(
            cast(type, IBackendRequestPreparation)
        )
        non_streaming_handler: INonStreamingBackendResponseHandler = (
            provider.get_required_service(
                cast(type, INonStreamingBackendResponseHandler)
            )
        )
        streaming_handler: IStreamingBackendResponseHandler = (
            provider.get_required_service(cast(type, IStreamingBackendResponseHandler))
        )

        # Optional collaborators (kept for backward compatibility)
        history_compaction_service = provider.get_service(HistoryCompactionService)
        config = provider.get_required_service(AppConfig)

        # Request deduplication service (extracted to helper for CC reduction)
        dedup_service: RequestDeduplicationService | None = (
            _create_deduplication_service(provider, config)
        )

        return BackendRequestManager(
            backend_processor,
            response_processor,
            angel_service_factory,
            request_preparation,
            non_streaming_handler,
            streaming_handler,
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


def _register_request_processor(services: ServiceCollection) -> None:
    """Register RequestProcessor and IRequestProcessor."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.backend_request_manager_interface import (
        IBackendRequestManager,
    )
    from src.core.interfaces.command_processor_interface import ICommandProcessor
    from src.core.interfaces.model_replacement_service_interface import (
        IModelReplacementService,
    )
    from src.core.interfaces.request_processor_interface import IRequestProcessor
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
    from src.core.services.request_processor_service import RequestProcessor

    def _response_processor_factory(provider: IServiceProvider) -> RequestProcessor:
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
