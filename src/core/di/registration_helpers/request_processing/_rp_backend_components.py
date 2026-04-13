"""
Backend request handling component registrations.

Registers:
- StructuredOutputEnforcer / IStructuredOutputEnforcer
- ToolCallRetryCoordinator / IToolCallRetryCoordinator
- BackendRequestPreparationService / IBackendRequestPreparation
- LoopDetectorFactory / ILoopDetectorFactory
- QualityVerifierStreamVerifier / IQualityVerifierStreamVerifier
- BackendStreamingResponseHandler (concrete; no legacy split-handler interface key)
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
    _register_backend_request_preparation_service(services)
    _register_loop_detector_factory(services)
    _register_quality_verifier_stream_verifier(services)
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
                f"Failed to register IStructuredOutputEnforcer interface: {e}",
                exc_info=True,
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
        from src.core.interfaces.non_forwardable_interface import (
            INonForwardableMessageIdentityService,
            INonForwardableMessageRegistry,
        )

        backend_processor: IBackendProcessor = provider.get_required_service(
            cast(type, IBackendProcessor)  # type: ignore[type-abstract]
        )
        cancellation_coordinator = provider.get_service(
            cast(type, ISessionCancellationCoordinator)
        )
        # Get non-forwardable services (optional - may not be registered)
        non_forwardable_registry = provider.get_service(
            cast(type, INonForwardableMessageRegistry)
        )
        non_forwardable_identity_service = provider.get_service(
            cast(type, INonForwardableMessageIdentityService)
        )
        return ToolCallRetryCoordinator(
            backend_processor=backend_processor,
            cancellation_coordinator=cancellation_coordinator,
            non_forwardable_registry=non_forwardable_registry,
            non_forwardable_identity_service=non_forwardable_identity_service,
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
                f"Failed to register IToolCallRetryCoordinator interface: {e}",
                exc_info=True,
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
    from src.core.interfaces.tool_output_compression_interface import (
        IToolOutputCompressionService,
    )
    from src.core.services.backend_request_preparation_service import (
        BackendRequestPreparationService,
    )
    from src.core.services.legacy_compression_compatibility_resolver import (
        LegacyCompressionCompatibilityResolver,
    )

    def _backend_request_preparation_factory(
        provider: IServiceProvider,
    ) -> BackendRequestPreparationService:
        history_compaction_service = provider.get_service(
            cast(type, IHistoryCompactionService)
        )
        tool_output_compression_service = provider.get_service(
            cast(type, IToolOutputCompressionService)
        )
        legacy_compression_compatibility_resolver = provider.get_service(
            LegacyCompressionCompatibilityResolver
        )
        config = provider.get_service(AppConfig)
        return BackendRequestPreparationService(
            history_compaction_service=history_compaction_service,
            config=config,
            tool_output_compression_service=tool_output_compression_service,
            legacy_compression_compatibility_resolver=legacy_compression_compatibility_resolver,
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
                f"Failed to register IBackendRequestPreparation interface: {e}",
                exc_info=True,
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
            logger.warning(
                "Failed to register ILoopDetectorFactory interface: %s",
                e,
                exc_info=True,
            )


def _register_quality_verifier_stream_verifier(services: ServiceCollection) -> None:
    """Register QualityVerifierStreamVerifier and IQualityVerifierStreamVerifier."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.backend_request_manager_components import (
        IQualityVerifierStreamVerifier,
    )
    from src.core.interfaces.quality_verifier_service_interface import (
        IQualityVerifierServiceFactory,
    )
    from src.core.interfaces.quality_verifier_turn_ledger_interface import (
        IQualityVerifierTurnLedger,
    )
    from src.core.interfaces.session_cancellation_coordinator_interface import (
        ISessionCancellationCoordinator,
    )
    from src.core.services.backend_request_manager.quality_verifier_stream_verifier import (
        QualityVerifierStreamVerifier,
    )

    def _quality_verifier_stream_verifier_factory(
        provider: IServiceProvider,
    ) -> QualityVerifierStreamVerifier:
        quality_verifier_service_factory: IQualityVerifierServiceFactory = (
            provider.get_required_service(cast(type, IQualityVerifierServiceFactory))
        )
        cancellation_coordinator = provider.get_service(
            cast(type, ISessionCancellationCoordinator)
        )
        turn_ledger: IQualityVerifierTurnLedger = provider.get_required_service(
            cast(type, IQualityVerifierTurnLedger)  # type: ignore[type-abstract]
        )
        return QualityVerifierStreamVerifier(
            quality_verifier_service_factory=quality_verifier_service_factory,
            provider=provider,
            cancellation_coordinator=cancellation_coordinator,
            turn_ledger=turn_ledger,
        )

    register_singleton_if_absent(
        services,
        QualityVerifierStreamVerifier,
        implementation_factory=_quality_verifier_stream_verifier_factory,
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, IQualityVerifierStreamVerifier),
            implementation_factory=_quality_verifier_stream_verifier_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to register IQualityVerifierStreamVerifier interface: %s",
                e,
                exc_info=True,
            )


def _register_backend_streaming_response_handler(
    services: ServiceCollection,
) -> None:
    """Register BackendStreamingResponseHandler singleton."""
    from src.core.di.registrations._shared import register_singleton_if_absent
    from src.core.interfaces.backend_processor_interface import IBackendProcessor
    from src.core.interfaces.backend_request_manager_components import (
        ILoopDetectorFactory,
        IQualityVerifierStreamVerifier,
        IStructuredOutputEnforcer,
        IToolCallRetryCoordinator,
    )
    from src.core.interfaces.backend_work_guard_interface import IBackendWorkGuard
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
        from src.core.config.models.canonical_request_processing import (
            CanonicalRequestProcessingConfig,
        )

        response_processor: IResponseProcessor = provider.get_required_service(
            cast(type, IResponseProcessor)  # type: ignore[type-abstract]
        )
        loop_detector_factory: ILoopDetectorFactory = provider.get_required_service(
            cast(type, ILoopDetectorFactory)
        )
        quality_verifier_stream_verifier: IQualityVerifierStreamVerifier = (
            provider.get_required_service(cast(type, IQualityVerifierStreamVerifier))
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
        backend_work_guard = provider.get_service(cast(type, IBackendWorkGuard))
        structured_output_enforcer = provider.get_service(
            cast(type, IStructuredOutputEnforcer)  # type: ignore[type-abstract]
        )

        # Extract empty stream recovery config (optional, with defaults)
        empty_stream_recovery_prompt: str | None = None
        max_empty_stream_retries: int | None = None
        try:
            app_config = provider.get_service(AppConfig)
            if app_config is not None:
                canonical_config = getattr(
                    app_config, "canonical_request_processing", None
                )
                if isinstance(canonical_config, CanonicalRequestProcessingConfig):
                    empty_stream_recovery_prompt = (
                        canonical_config.empty_stream_recovery_prompt
                    )
                    max_empty_stream_retries = canonical_config.max_empty_stream_retries
        except Exception:
            # Fail-open: use defaults if config lookup fails
            pass

        return BackendStreamingResponseHandler(
            response_processor=response_processor,
            loop_detector_factory=loop_detector_factory,
            quality_verifier_stream_verifier=quality_verifier_stream_verifier,
            tool_call_retry_coordinator=tool_call_retry_coordinator,
            backend_processor=backend_processor,
            cancellation_coordinator=cancellation_coordinator,
            backend_work_guard=backend_work_guard,
            structured_output_enforcer=structured_output_enforcer,
            empty_stream_recovery_prompt=empty_stream_recovery_prompt,
            max_empty_stream_retries=max_empty_stream_retries,
        )

    register_singleton_if_absent(
        services,
        BackendStreamingResponseHandler,
        implementation_factory=_backend_streaming_response_handler_factory,
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
            logger.warning(
                "Failed to register ILoopDetector interface: %s", e, exc_info=True
            )
