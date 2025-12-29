"""
Backend request handling component registrations.

Registers:
- StructuredOutputEnforcer / IStructuredOutputEnforcer
- ToolCallRetryCoordinator / IToolCallRetryCoordinator
- BackendNonStreamingResponseHandler / INonStreamingBackendResponseHandler
- BackendRequestPreparationService / IBackendRequestPreparation
- LoopDetectorFactory / ILoopDetectorFactory
- AngelStreamVerifier / IAngelStreamVerifier
- BackendStreamingResponseHandler / IStreamingBackendResponseHandler
- LoopDetector / ILoopDetector (HybridLoopDetector)
"""

from __future__ import annotations

import logging
from typing import NamedTuple, cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


class HybridDetectorConfig(NamedTuple):
    """Configuration for HybridLoopDetector.

    Contains both short and long pattern detection configurations.

    Attributes:
        short_config: Configuration for short pattern detection
        long_config: Configuration for long pattern detection
    """

    short_config: dict
    long_config: dict


def register_backend_component_services(services: ServiceCollection) -> None:
    """Register backend request handling components."""
    _register_structured_output_enforcer(services)
    _register_tool_call_retry_coordinator(services)
    _register_backend_non_streaming_response_handler(services)
    _register_backend_request_preparation_service(services)
    _register_loop_detector_factory(services)
    _register_angel_stream_verifier(services)
    _register_backend_streaming_response_handler(services)
    _register_loop_detector(services)


def _register_structured_output_enforcer(services: ServiceCollection) -> None:
    """Register StructuredOutputEnforcer and IStructuredOutputEnforcer."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.backend_request_manager_components import (
        IStructuredOutputEnforcer,
    )
    from src.core.services.structured_output_enforcer import StructuredOutputEnforcer

    def _structured_output_enforcer_factory(
        provider: IServiceProvider,
    ) -> StructuredOutputEnforcer:
        return StructuredOutputEnforcer(provider=provider)

    register_singleton_if_absent(
        services,
        StructuredOutputEnforcer,
        implementation_factory=_structured_output_enforcer_factory,
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, IStructuredOutputEnforcer),
            implementation_factory=_structured_output_enforcer_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"Failed to register IStructuredOutputEnforcer interface: {e}"
            )


def _register_tool_call_retry_coordinator(services: ServiceCollection) -> None:
    """Register ToolCallRetryCoordinator and IToolCallRetryCoordinator."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.backend_processor_interface import IBackendProcessor
    from src.core.interfaces.backend_request_manager_components import (
        IToolCallRetryCoordinator,
    )
    from src.core.interfaces.session_cancellation_coordinator_interface import (
        ISessionCancellationCoordinator,
    )
    from src.core.services.tool_call_retry_coordinator import ToolCallRetryCoordinator

    def _tool_call_retry_coordinator_factory(
        provider: IServiceProvider,
    ) -> ToolCallRetryCoordinator:
        backend_processor: IBackendProcessor = provider.get_required_service(
            cast(type, IBackendProcessor)  # type: ignore[type-abstract]
        )
        cancellation_coordinator = provider.get_service(
            cast(type, ISessionCancellationCoordinator)
        )
        return ToolCallRetryCoordinator(
            backend_processor=backend_processor,
            cancellation_coordinator=cancellation_coordinator,
        )

    register_singleton_if_absent(
        services,
        ToolCallRetryCoordinator,
        implementation_factory=_tool_call_retry_coordinator_factory,
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, IToolCallRetryCoordinator),
            implementation_factory=_tool_call_retry_coordinator_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"Failed to register IToolCallRetryCoordinator interface: {e}"
            )


def _register_backend_non_streaming_response_handler(
    services: ServiceCollection,
) -> None:
    """Register BackendNonStreamingResponseHandler and INonStreamingBackendResponseHandler."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.backend_processor_interface import IBackendProcessor
    from src.core.interfaces.backend_request_manager_components import (
        INonStreamingBackendResponseHandler,
        IStructuredOutputEnforcer,
        IToolCallRetryCoordinator,
    )
    from src.core.interfaces.response_processor_interface import IResponseProcessor
    from src.core.services.backend_non_streaming_response_handler import (
        BackendNonStreamingResponseHandler,
    )

    def _backend_non_streaming_response_handler_factory(
        provider: IServiceProvider,
    ) -> BackendNonStreamingResponseHandler:
        response_processor: IResponseProcessor = provider.get_required_service(
            cast(type, IResponseProcessor)  # type: ignore[type-abstract]
        )
        structured_output_enforcer: (
            IStructuredOutputEnforcer
        ) = provider.get_required_service(
            cast(type, IStructuredOutputEnforcer)  # type: ignore[type-abstract]
        )
        tool_call_retry_coordinator: (
            IToolCallRetryCoordinator
        ) = provider.get_required_service(
            cast(type, IToolCallRetryCoordinator)  # type: ignore[type-abstract]
        )
        backend_processor: IBackendProcessor = provider.get_required_service(
            cast(type, IBackendProcessor)  # type: ignore[type-abstract]
        )

        # Get cancellation coordinator (optional, registered in streaming phase)
        cancellation_coordinator = None
        try:
            from src.core.interfaces.session_cancellation_coordinator_interface import (
                ISessionCancellationCoordinator,
            )

            cancellation_coordinator = provider.get_service(
                cast(type, ISessionCancellationCoordinator)
            )
        except Exception:
            # Cancellation coordinator not available (optional dependency)
            # Log unexpected errors during service lookup to aid debugging
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to get ISessionCancellationCoordinator during "
                    "BackendNonStreamingResponseHandler registration (optional dependency)",
                    exc_info=True,
                )

        return BackendNonStreamingResponseHandler(
            response_processor=response_processor,
            structured_output_enforcer=structured_output_enforcer,
            tool_call_retry_coordinator=tool_call_retry_coordinator,
            backend_processor=backend_processor,
            cancellation_coordinator=cancellation_coordinator,
        )

    register_singleton_if_absent(
        services,
        BackendNonStreamingResponseHandler,
        implementation_factory=_backend_non_streaming_response_handler_factory,
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, INonStreamingBackendResponseHandler),
            implementation_factory=_backend_non_streaming_response_handler_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"Failed to register INonStreamingBackendResponseHandler interface: {e}"
            )


def _register_backend_request_preparation_service(
    services: ServiceCollection,
) -> None:
    """Register BackendRequestPreparationService and IBackendRequestPreparation."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.backend_request_manager_components import (
        IBackendRequestPreparation,
    )
    from src.core.interfaces.history_compaction_interface import (
        IHistoryCompactionService,
    )
    from src.core.services.backend_request_preparation_service import (
        BackendRequestPreparationService,
    )

    def _backend_request_preparation_factory(
        provider: IServiceProvider,
    ) -> BackendRequestPreparationService:
        history_compaction_service = provider.get_service(
            cast(type, IHistoryCompactionService)
        )
        config = provider.get_service(AppConfig)
        return BackendRequestPreparationService(
            history_compaction_service=history_compaction_service,
            config=config,
        )

    register_singleton_if_absent(
        services,
        BackendRequestPreparationService,
        implementation_factory=_backend_request_preparation_factory,
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, IBackendRequestPreparation),
            implementation_factory=_backend_request_preparation_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"Failed to register IBackendRequestPreparation interface: {e}"
            )


def _register_loop_detector_factory(services: ServiceCollection) -> None:
    """Register LoopDetectorFactory and ILoopDetectorFactory."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.backend_request_manager_components import (
        ILoopDetectorFactory,
    )
    from src.core.services.backend_request_manager.loop_detector_factory import (
        LoopDetectorFactory,
    )

    def _loop_detector_factory_factory(
        provider: IServiceProvider,
    ) -> LoopDetectorFactory:
        return LoopDetectorFactory(provider=provider)

    register_singleton_if_absent(
        services,
        LoopDetectorFactory,
        implementation_factory=_loop_detector_factory_factory,
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, ILoopDetectorFactory),
            implementation_factory=_loop_detector_factory_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Failed to register ILoopDetectorFactory interface: %s", e)


def _register_angel_stream_verifier(services: ServiceCollection) -> None:
    """Register AngelStreamVerifier and IAngelStreamVerifier."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.angel_service_interface import IAngelServiceFactory
    from src.core.interfaces.backend_request_manager_components import (
        IAngelStreamVerifier,
    )
    from src.core.interfaces.session_cancellation_coordinator_interface import (
        ISessionCancellationCoordinator,
    )
    from src.core.services.backend_request_manager.angel_stream_verifier import (
        AngelStreamVerifier,
    )

    def _angel_stream_verifier_factory(
        provider: IServiceProvider,
    ) -> AngelStreamVerifier:
        angel_service_factory: IAngelServiceFactory = provider.get_required_service(
            cast(type, IAngelServiceFactory)
        )
        cancellation_coordinator = provider.get_service(
            cast(type, ISessionCancellationCoordinator)
        )
        return AngelStreamVerifier(
            angel_service_factory=angel_service_factory,
            provider=provider,
            cancellation_coordinator=cancellation_coordinator,
        )

    register_singleton_if_absent(
        services,
        AngelStreamVerifier,
        implementation_factory=_angel_stream_verifier_factory,
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, IAngelStreamVerifier),
            implementation_factory=_angel_stream_verifier_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Failed to register IAngelStreamVerifier interface: %s", e)


def _register_backend_streaming_response_handler(
    services: ServiceCollection,
) -> None:
    """Register BackendStreamingResponseHandler and IStreamingBackendResponseHandler."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.backend_processor_interface import IBackendProcessor
    from src.core.interfaces.backend_request_manager_components import (
        IAngelStreamVerifier,
        ILoopDetectorFactory,
        IStreamingBackendResponseHandler,
        IToolCallRetryCoordinator,
    )
    from src.core.interfaces.response_processor_interface import IResponseProcessor
    from src.core.interfaces.session_cancellation_coordinator_interface import (
        ISessionCancellationCoordinator,
    )
    from src.core.services.backend_request_manager.streaming_response_handler import (
        BackendStreamingResponseHandler,
    )

    def _backend_streaming_response_handler_factory(
        provider: IServiceProvider,
    ) -> BackendStreamingResponseHandler:
        response_processor: IResponseProcessor = provider.get_required_service(
            cast(type, IResponseProcessor)  # type: ignore[type-abstract]
        )
        loop_detector_factory: ILoopDetectorFactory = provider.get_required_service(
            cast(type, ILoopDetectorFactory)
        )
        angel_stream_verifier: IAngelStreamVerifier = provider.get_required_service(
            cast(type, IAngelStreamVerifier)
        )
        tool_call_retry_coordinator: IToolCallRetryCoordinator = (
            provider.get_required_service(cast(type, IToolCallRetryCoordinator))
        )
        backend_processor: IBackendProcessor = provider.get_required_service(
            cast(type, IBackendProcessor)  # type: ignore[type-abstract]
        )
        cancellation_coordinator = provider.get_service(
            cast(type, ISessionCancellationCoordinator)
        )
        return BackendStreamingResponseHandler(
            response_processor=response_processor,
            loop_detector_factory=loop_detector_factory,
            angel_stream_verifier=angel_stream_verifier,
            tool_call_retry_coordinator=tool_call_retry_coordinator,
            backend_processor=backend_processor,
            cancellation_coordinator=cancellation_coordinator,
        )

    register_singleton_if_absent(
        services,
        BackendStreamingResponseHandler,
        implementation_factory=_backend_streaming_response_handler_factory,
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, IStreamingBackendResponseHandler),
            implementation_factory=_backend_streaming_response_handler_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                f"Failed to register IStreamingBackendResponseHandler interface: {e}"
            )


def _should_use_noop_detector(config: AppConfig | None) -> bool:
    """Check if NoOp detector should be used.

    Returns:
        True if NoOpLoopDetector should be used, False otherwise.
    """
    if not config:
        return False
    if not hasattr(config, "session"):
        return False
    if not hasattr(config.session, "loop_detection"):
        return False

    loop_config = config.session.loop_detection  # type: ignore[attr-defined]
    return not loop_config or not loop_config.get("enabled", True)


def _create_hybrid_detector_config() -> HybridDetectorConfig:
    """Create configuration for HybridLoopDetector.

    Returns:
        HybridDetectorConfig containing both short and long configurations.
    """
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

    return HybridDetectorConfig(short_config=short_config, long_config=long_config)


def _register_loop_detector(services: ServiceCollection) -> None:
    """Register LoopDetector and ILoopDetector."""
    from src.core.di.registrations._shared import register_transient_if_absent
    from src.core.interfaces.loop_detector_interface import ILoopDetector
    from src.loop_detection.hybrid_detector import HybridLoopDetector

    def _loop_detector_factory(provider: IServiceProvider) -> ILoopDetector:
        app_config = provider.get_service(AppConfig)

        if _should_use_noop_detector(app_config):
            from src.loop_detection.detector import NoOpLoopDetector

            return NoOpLoopDetector()

        hybrid_config = _create_hybrid_detector_config()

        return HybridLoopDetector(
            short_detector_config=hybrid_config.short_config,
            long_detector_config=hybrid_config.long_config,
        )

    register_transient_if_absent(
        services, HybridLoopDetector, implementation_factory=_loop_detector_factory
    )
    try:
        register_transient_if_absent(
            services,
            cast(type, ILoopDetector),
            implementation_factory=_loop_detector_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Failed to register ILoopDetector interface: %s", e)
