"""
Streaming pipeline and middleware registrations.

Registers:
- StreamingContextRegistry
- MiddlewareApplicationManager (with all features)
- MiddlewareApplicationProcessor
- StreamNormalizer / IStreamNormalizer / IProcessingStreamNormalizer
- ToolCallReactorMiddleware (legacy)
- LoopDetectionProcessor
"""

from __future__ import annotations

import logging
import os
from typing import Any, cast

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import (
    register_singleton_if_absent,
)
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_streaming_pipeline_services(
    services: ServiceCollection,
    app_config: AppConfig | None,
) -> None:
    """Register all streaming pipeline services.

    Args:
        services: The service collection to register into
        app_config: Optional application configuration
    """
    _register_streaming_context_registry(services)
    _register_middleware_application_manager(services)
    _register_middleware_application_processor(services)
    _register_stream_normalizer(services)
    _register_tool_call_reactor_middleware_legacy(services)
    _register_loop_detection_processor(services)


def _register_streaming_context_registry(services: ServiceCollection) -> None:
    """Register StreamingContextRegistry as singleton using the global instance.

    This ensures that components using DI and components using the global accessor
    share the same registry instance, allowing cleanup mechanisms (run by DI components)
    to effectively manage memory for all users.
    """
    from src.core.services.streaming.stream_context_registry import (
        StreamingContextRegistry,
        get_global_streaming_context_registry,
    )

    def factory(provider: IServiceProvider) -> StreamingContextRegistry:
        return get_global_streaming_context_registry()

    register_singleton_if_absent(
        services,
        StreamingContextRegistry,
        implementation_factory=factory,
    )


def _register_middleware_application_manager(services: ServiceCollection) -> None:
    """Register MiddlewareApplicationManager with feature configuration."""
    from src.core.services.middleware_application_manager import (
        MiddlewareApplicationManager,
    )

    def _middleware_application_manager_factory(
        provider: IServiceProvider,
    ) -> MiddlewareApplicationManager:
        from src.core.app.middleware.json_repair_middleware import JsonRepairFeature
        from src.core.config.app_config import AppConfig
        from src.core.interfaces.response_processor_interface import (
            IResponseFeature,
            IResponseMiddleware,
        )
        from src.core.services.application_state_service import ApplicationStateService
        from src.core.services.empty_response_middleware import EmptyResponseFeature
        from src.core.services.json_repair_service import JsonRepairService
        from src.core.services.tool_call_loop_middleware import (
            ToolCallLoopDetectionFeature,
        )
        from src.tool_call_loop.lifecycle_registry import ToolCallLifecycleRegistry

        cfg: AppConfig = provider.get_required_service(AppConfig)
        features: list[IResponseFeature | IResponseMiddleware] = []

        if getattr(cfg.empty_response, "enabled", True):
            features.append(
                EmptyResponseFeature(
                    enabled=True,
                    max_retries=getattr(cfg.empty_response, "max_retries", 1),
                    count_reasoning_for_empty_stream=getattr(
                        cfg.empty_response,
                        "count_reasoning_for_empty_stream",
                        True,
                    ),
                )
            )

        # Edit-precision response-side detection (optional)
        from src.core.services.edit_precision_response_middleware import (
            EditPrecisionFeature,
        )

        app_state = provider.get_required_service(ApplicationStateService)
        features.append(EditPrecisionFeature(app_state))

        # Think tags fix feature (optional)
        if getattr(cfg.session, "fix_think_tags_enabled", False):
            from src.core.services.think_tags_fix_middleware import (
                ThinkTagsFixFeature,
            )

            buffer_size = getattr(
                cfg.session, "fix_think_tags_streaming_buffer_size", 4096
            )
            features.append(
                ThinkTagsFixFeature(enabled=True, streaming_buffer_size=buffer_size)
            )

        if getattr(cfg.session, "json_repair_enabled", False):
            json_service: JsonRepairService | None = None
            import contextlib

            with contextlib.suppress(RuntimeError):
                # Optional service not registered
                json_service = provider.get_service(JsonRepairService)
            if json_service is not None:
                features.append(JsonRepairFeature(cfg, json_service))

        lifecycle_registry = provider.get_service(ToolCallLifecycleRegistry)
        if lifecycle_registry is not None:
            features.append(
                ToolCallLoopDetectionFeature(
                    lifecycle_registry=lifecycle_registry,
                )
            )

        # Add tool call reactor feature (optional - only if services are available)
        from src.core.interfaces.tool_call_reactor_orchestrator_interface import (
            IToolCallReactorOrchestrator,
        )
        from src.core.interfaces.tool_call_stream_context_resolver_interface import (
            IToolCallStreamContextResolver,
        )
        from src.core.services.tool_call_reactor_middleware import (
            ToolCallReactorFeature,
        )
        from src.core.services.tool_call_reactor_service import (
            ToolCallReactorService,
        )

        tool_call_reactor = provider.get_service(ToolCallReactorService)
        orchestrator = provider.get_service(cast(type, IToolCallReactorOrchestrator))  # type: ignore[type-abstract]
        stream_context_resolver = provider.get_service(cast(type, IToolCallStreamContextResolver))  # type: ignore[type-abstract]

        if (
            tool_call_reactor is not None
            and orchestrator is not None
            and stream_context_resolver is not None
        ):
            enabled = getattr(cfg.session, "tool_call_reactor", None)
            enabled = (
                getattr(enabled, "enabled", False) if enabled is not None else False
            )

            features.append(
                ToolCallReactorFeature(
                    orchestrator=orchestrator,
                    stream_context_resolver=stream_context_resolver,
                    tool_call_reactor=tool_call_reactor,
                    enabled=enabled,
                )
            )

        return MiddlewareApplicationManager(features)

    register_singleton_if_absent(
        services,
        MiddlewareApplicationManager,
        implementation_factory=_middleware_application_manager_factory,
    )

    # Register legacy ToolCallReactorMiddleware for backward compatibility
    _register_tool_call_reactor_middleware_legacy(services)


def _register_middleware_application_processor(services: ServiceCollection) -> None:
    """Register MiddlewareApplicationProcessor."""
    from src.core.services.streaming.middleware_application_processor import (
        MiddlewareApplicationProcessor,
    )
    from src.core.services.streaming.stream_context_registry import (
        StreamingContextRegistry,
    )

    def _middleware_application_processor_factory(
        provider: IServiceProvider,
    ) -> MiddlewareApplicationProcessor:
        from src.core.interfaces.application_state_interface import IApplicationState
        from src.core.services.middleware_application_manager import (
            MiddlewareApplicationManager,
        )

        manager: MiddlewareApplicationManager = provider.get_required_service(
            MiddlewareApplicationManager
        )
        app_state: IApplicationState = provider.get_required_service(
            cast(type, IApplicationState)  # type: ignore[type-abstract]
        )
        registry: StreamingContextRegistry = provider.get_required_service(
            StreamingContextRegistry
        )

        from src.core.domain.configuration.loop_detection_config import (
            LoopDetectionConfiguration,
        )
        from src.tool_call_loop.config import ToolCallLoopConfig

        env_config = ToolCallLoopConfig.from_env_vars(dict(os.environ))
        loop_config = (
            LoopDetectionConfiguration()
            .with_tool_loop_detection_enabled(env_config.enabled)
            .with_tool_loop_max_repeats(env_config.max_repeats)
            .with_tool_loop_ttl_seconds(env_config.ttl_seconds)
            .with_tool_loop_mode(env_config.mode)
        )

        return MiddlewareApplicationProcessor(
            manager.middleware,
            default_loop_config=loop_config,
            app_state=app_state,
            registry=registry,
        )

    register_singleton_if_absent(
        services,
        MiddlewareApplicationProcessor,
        implementation_factory=_middleware_application_processor_factory,
    )


def _register_stream_normalizer(services: ServiceCollection) -> None:
    """Register StreamNormalizer with IProcessingStreamNormalizer interface binding."""
    from src.core.domain.streaming_response_processor import (
        LoopDetectionProcessor,
    )
    from src.core.interfaces.loop_detector_interface import ILoopDetector
    from src.core.interfaces.streaming_response_processor_interface import (
        IStreamNormalizer,
    )
    from src.core.interfaces.tool_call_repair_service_interface import (
        IToolCallRepairService,
    )
    from src.core.services.streaming.content_accumulation_processor import (
        ContentAccumulationProcessor,
    )
    from src.core.services.streaming.middleware_application_processor import (
        MiddlewareApplicationProcessor,
    )
    from src.core.services.streaming.stream_context_registry import (
        StreamingContextRegistry,
    )

    # Alias for backward compatibility
    IProcessingStreamNormalizer = IStreamNormalizer
    from src.core.services.streaming.stream_normalizer import StreamNormalizer
    from src.core.services.streaming.tool_call_repair_processor import (
        ToolCallRepairProcessor,
    )

    def _stream_normalizer_factory(provider: IServiceProvider) -> StreamNormalizer:
        """Create StreamNormalizer with proper processor chain."""
        processors: list[Any] = []

        # ToolCallRepairProcessor (requires IToolCallRepairService)
        tool_call_repair_service = provider.get_service(
            cast(type, IToolCallRepairService)  # type: ignore[type-abstract]
        )
        if tool_call_repair_service is not None:
            registry = provider.get_required_service(StreamingContextRegistry)
            processors.append(
                ToolCallRepairProcessor(
                    tool_call_repair_service=tool_call_repair_service,
                    registry=registry,
                )
            )

        # LoopDetectionProcessor (requires ILoopDetector)
        loop_detector = provider.get_service(cast(type, ILoopDetector))  # type: ignore[type-abstract]
        if loop_detector is not None:
            # Try to get pre-registered LoopDetectionProcessor first
            loop_processor = provider.get_service(LoopDetectionProcessor)
            if loop_processor is not None:
                processors.append(loop_processor)
            else:
                # Create new instance if not registered
                processors.append(
                    LoopDetectionProcessor(loop_detector_factory=lambda: loop_detector)
                )

        # ContentAccumulationProcessor (requires StreamingContextRegistry)
        registry = provider.get_required_service(StreamingContextRegistry)
        processors.append(
            ContentAccumulationProcessor(
                max_buffer_bytes=10 * 1024 * 1024, registry=registry
            )
        )

        # EndOfSessionStreamProcessor (requires IEndOfSessionService)
        from src.core.interfaces.end_of_session_service_interface import (
            IEndOfSessionService,
        )

        eos_service = provider.get_service(cast(type, IEndOfSessionService))  # type: ignore[type-abstract]
        if eos_service is not None:
            config = provider.get_required_service(AppConfig)
            eos_config = config.end_of_session
            from src.core.services.streaming.end_of_session_stream_processor import (
                EndOfSessionStreamProcessor,
            )

            processors.append(
                EndOfSessionStreamProcessor(
                    end_of_session_service=eos_service,
                    config=eos_config,
                )
            )

        # MiddlewareApplicationProcessor (requires MiddlewareApplicationManager)
        middleware_processor = provider.get_service(MiddlewareApplicationProcessor)
        if middleware_processor is not None:
            processors.append(middleware_processor)

        return StreamNormalizer(processors=processors)

    register_singleton_if_absent(
        services,
        StreamNormalizer,
        implementation_factory=_stream_normalizer_factory,
    )

    # Bind interface to concrete type by resolving it from provider
    def _istream_normalizer_factory(
        provider: IServiceProvider,
    ) -> StreamNormalizer:
        return provider.get_required_service(StreamNormalizer)

    # Register IStreamNormalizer interface (primary interface)
    register_singleton_if_absent(
        services,
        cast(type, IStreamNormalizer),  # type: ignore[type-abstract]
        implementation_factory=_istream_normalizer_factory,  # type: ignore[type-abstract]
    )
    # Also register IProcessingStreamNormalizer alias for backward compatibility
    register_singleton_if_absent(
        services,
        cast(type, IProcessingStreamNormalizer),  # type: ignore[type-abstract]
        implementation_factory=_istream_normalizer_factory,  # type: ignore[type-abstract]
    )


def _register_tool_call_reactor_middleware_legacy(services: ServiceCollection) -> None:
    """Register legacy ToolCallReactorMiddleware for backward compatibility."""
    from src.core.services.tool_call_reactor_middleware import (
        ToolCallReactorMiddleware,
    )

    def tool_call_reactor_middleware_factory(
        provider: IServiceProvider,
    ) -> ToolCallReactorMiddleware:
        """Factory for creating legacy ToolCallReactorMiddleware."""
        from src.core.config.app_config import AppConfig
        from src.core.interfaces.tool_call_reactor_orchestrator_interface import (
            IToolCallReactorOrchestrator,
        )
        from src.core.interfaces.tool_call_stream_context_resolver_interface import (
            IToolCallStreamContextResolver,
        )
        from src.core.services.tool_call_reactor_service import (
            ToolCallReactorService,
        )

        config = provider.get_service(AppConfig)
        tool_call_reactor = provider.get_service(ToolCallReactorService)
        orchestrator = provider.get_service(cast(type, IToolCallReactorOrchestrator))  # type: ignore[type-abstract]
        stream_context_resolver = provider.get_service(cast(type, IToolCallStreamContextResolver))  # type: ignore[type-abstract]

        enabled = False
        if config is not None:
            reactor_config = getattr(config.session, "tool_call_reactor", None)
            if reactor_config is not None:
                enabled = getattr(reactor_config, "enabled", False)

        # Create middleware only if all services are available
        # If not available, create a disabled instance with None dependencies
        # This allows tests to resolve the service even if dependencies aren't ready
        if (
            tool_call_reactor is not None
            and orchestrator is not None
            and stream_context_resolver is not None
        ):
            return ToolCallReactorMiddleware(
                orchestrator=orchestrator,
                stream_context_resolver=stream_context_resolver,
                tool_call_reactor=tool_call_reactor,
                enabled=enabled,
            )

        # Create disabled instance for backward compatibility
        # Use mock objects if needed - but this should only happen in tests
        # In production, all dependencies should be available
        from unittest.mock import MagicMock

        return ToolCallReactorMiddleware(
            orchestrator=orchestrator or MagicMock(),  # type: ignore[arg-type]
            stream_context_resolver=stream_context_resolver or MagicMock(),  # type: ignore[arg-type]
            tool_call_reactor=tool_call_reactor or MagicMock(),  # type: ignore[arg-type]
            enabled=False,
        )

    register_singleton_if_absent(
        services,
        ToolCallReactorMiddleware,
        implementation_factory=tool_call_reactor_middleware_factory,
    )


def _register_loop_detection_processor(services: ServiceCollection) -> None:
    """Register LoopDetectionProcessor if ILoopDetector is available."""
    from src.core.domain.streaming_response_processor import (
        LoopDetectionProcessor,
    )
    from src.core.interfaces.loop_detector_interface import ILoopDetector

    def loop_detection_processor_factory(
        provider: IServiceProvider,
    ) -> LoopDetectionProcessor:
        """Factory for creating LoopDetectionProcessor if loop detector is available."""
        loop_detector = provider.get_service(cast(type, ILoopDetector))  # type: ignore[type-abstract]
        if loop_detector is not None:
            return LoopDetectionProcessor(loop_detector_factory=lambda: loop_detector)
        # If loop detector is not available, create processor with a no-op factory
        # This ensures the service is always registered for tests
        from src.loop_detection.hybrid_detector import HybridLoopDetector

        return LoopDetectionProcessor(
            loop_detector_factory=lambda: HybridLoopDetector()
        )

    # Register as singleton - always creates an instance
    register_singleton_if_absent(
        services,
        LoopDetectionProcessor,
        implementation_factory=loop_detection_processor_factory,
    )
