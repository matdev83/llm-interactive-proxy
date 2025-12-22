from collections.abc import Iterator  # Added import
from unittest.mock import Mock

import pytest
from src.core.common.exceptions import ServiceResolutionError
from src.core.di.container import ServiceCollection
from src.core.di.services import (
    get_service_provider,
    register_core_services,
    set_service_provider,
)
from src.core.domain.streaming_response_processor import LoopDetectionProcessor
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.response_parser_interface import IResponseParser
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.streaming_response_processor_interface import IStreamNormalizer
from src.core.interfaces.tool_call_repair_service_interface import (
    IToolCallRepairService,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService


class TestServiceRegistration:
    """Tests for DI service registrations."""

    @pytest.fixture(autouse=True)
    def setup(self) -> Iterator[None]:
        # Reset the global service provider before each test
        set_service_provider(None)
        yield
        set_service_provider(None)  # Clean up after test

    def test_stream_normalizer_registration(self) -> None:
        """Test that IStreamNormalizer resolves to StreamNormalizer as a singleton."""
        from typing import cast

        from src.core.config.app_config import AppConfig
        from src.core.di.registrations import core, streaming, tooling
        from src.core.interfaces.event_bus_interface import IEventBus
        from src.core.services.event_bus import EventBus

        services = ServiceCollection()
        config = AppConfig()

        # Register EventBus (required by EndOfSessionService which is used by StreamNormalizer)
        def event_bus_factory(provider: IServiceProvider) -> EventBus:
            return EventBus()

        services.add_singleton(EventBus, implementation_factory=event_bus_factory)
        services.add_singleton(
            cast(type, IEventBus),
            implementation_factory=lambda p: p.get_required_service(EventBus),
        )

        # Register core, tooling, and streaming services
        # (StreamNormalizer is now in streaming registrar, but depends on tooling services)
        core.register(services, config)
        tooling.register(services, config)
        streaming.register(services, config)
        provider = services.build_service_provider()

        # Resolve IStreamNormalizer
        normalizer1 = provider.get_required_service(IStreamNormalizer)  # type: ignore[type-abstract]
        normalizer2 = provider.get_required_service(IStreamNormalizer)  # type: ignore[type-abstract]

        # Assert correct type
        assert isinstance(normalizer1, StreamNormalizer)
        # Assert singleton behavior
        assert normalizer1 is normalizer2

    def test_tool_call_repair_service_registration(self) -> None:
        """Test that IToolCallRepairService resolves to ToolCallRepairService as a singleton."""
        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        # Resolve IToolCallRepairService
        repair_service1 = provider.get_required_service(IToolCallRepairService)  # type: ignore[type-abstract]
        repair_service2 = provider.get_required_service(IToolCallRepairService)  # type: ignore[type-abstract]

        # Assert correct type
        assert isinstance(repair_service1, ToolCallRepairService)
        # Assert singleton behavior
        assert repair_service1 is repair_service2

    def test_get_service_provider_global_access(self) -> None:
        """Test that get_service_provider returns the globally configured provider."""
        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()
        set_service_provider(provider)

        global_provider = get_service_provider()
        assert global_provider is provider

        normalizer = global_provider.get_required_service(IStreamNormalizer)  # type: ignore[type-abstract]
        assert isinstance(normalizer, StreamNormalizer)

    def test_get_service_collection_returns_empty_collection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ensure get_service_collection returns an empty ServiceCollection."""

        import src.core.di.services as services_module

        monkeypatch.setattr(services_module, "_service_collection", None, raising=False)

        collection = services_module.get_service_collection()

        # Should return a ServiceCollection without any services registered
        assert isinstance(collection, ServiceCollection)
        # The collection should be empty initially (only descriptors dict exists)
        assert hasattr(collection, "_descriptors")

    def test_get_service_provider_fails_fast_on_missing_services(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ensure get_service_provider fails fast instead of self-healing."""
        from src.core.di import provider_lifecycle

        minimal_services = ServiceCollection()
        minimal_provider = minimal_services.build_service_provider()
        provider_lifecycle.set_service_provider(minimal_provider)

        from src.core.services.tool_call_reactor_service import ToolCallReactorService

        # Missing service should raise ServiceResolutionError
        with pytest.raises(ServiceResolutionError):
            minimal_provider.get_required_service(ToolCallReactorService)

        # get_service_provider should return the provider as-is (no self-healing)
        retrieved_provider = provider_lifecycle.get_service_provider()
        assert retrieved_provider is minimal_provider

        # Provider should still not have the service
        assert retrieved_provider.get_service(ToolCallReactorService) is None

        # Attempting to get it should still fail
        with pytest.raises(ServiceResolutionError):
            retrieved_provider.get_required_service(ToolCallReactorService)

    def test_response_processor_streaming_pipeline_setup(self) -> None:
        """
        Test that ResponseProcessor is configured with StreamNormalizer and ToolCallRepairProcessor.

        After unified pipeline refactoring, ResponseProcessor uses the same streaming pipeline
        for both streaming and non-streaming responses. The middleware_application_manager
        parameter has been removed.
        """
        services = ServiceCollection()

        # Mock IApplicationState
        mock_app_state = Mock(spec=IApplicationState)
        mock_app_state.get_use_streaming_pipeline.return_value = True
        services.add_instance(IApplicationState, mock_app_state)

        # Import necessary classes for the local factory
        from typing import cast

        from src.core.domain.streaming_response_processor import IStreamProcessor
        from src.core.interfaces.streaming_response_processor_interface import (
            IStreamNormalizer,
        )
        from src.core.interfaces.tool_call_repair_service_interface import (
            IToolCallRepairService,
        )
        from src.core.services.response_processor_service import ResponseProcessor
        from src.core.services.streaming.stream_normalizer import StreamNormalizer
        from src.core.services.tool_call_repair_service import ToolCallRepairService
        from src.loop_detection.hybrid_detector import HybridLoopDetector

        # Define a local factory function to mimic the logic from services.py
        def response_processor_factory_for_test(
            provider: IServiceProvider,
        ) -> ResponseProcessor:
            response_parser: IResponseParser = provider.get_required_service(
                IResponseParser  # type: ignore[type-abstract]
            )

            processors: list[IStreamProcessor] = []

            tool_call_repair_service = provider.get_required_service(
                IToolCallRepairService  # type: ignore[type-abstract]
            )
            processors.append(ToolCallRepairProcessor(tool_call_repair_service))

            processors.append(
                LoopDetectionProcessor(
                    loop_detector_factory=lambda: HybridLoopDetector()
                )
            )

            stream_normalizer_instance = StreamNormalizer(processors=processors)

            # ResponseProcessor now uses unified pipeline (no middleware_application_manager)
            return ResponseProcessor(
                response_parser=response_parser,
                app_state=provider.get_required_service(
                    IApplicationState  # type: ignore[type-abstract]
                ),
                stream_normalizer=stream_normalizer_instance,
                loop_detector_factory=lambda: HybridLoopDetector(),
            )

        # Manually register required services
        services.add_singleton(ToolCallRepairService)
        services.add_singleton(
            cast(type, IToolCallRepairService), ToolCallRepairService
        )
        services.add_singleton(StreamNormalizer)
        services.add_singleton(cast(type, IStreamNormalizer), StreamNormalizer)
        services.add_singleton(
            ResponseProcessor,
            implementation_factory=response_processor_factory_for_test,
        )
        services.add_singleton(
            cast(type, IResponseProcessor),
            implementation_factory=response_processor_factory_for_test,
        )
        # Add mock service for required argument
        services.add_instance(IResponseParser, Mock(spec=IResponseParser))

        provider = services.build_service_provider()

        # Resolve ResponseProcessor (concrete type for internal inspection)
        response_processor = provider.get_required_service(ResponseProcessor)

        # Assert that StreamNormalizer is configured
        assert hasattr(response_processor, "_stream_normalizer")
        stream_normalizer = response_processor._stream_normalizer
        assert isinstance(stream_normalizer, StreamNormalizer)

        # Assert that StreamNormalizer has ToolCallRepairProcessor
        assert len(stream_normalizer._processors) == 2
        tool_call_processor = stream_normalizer._processors[0]
        assert isinstance(tool_call_processor, ToolCallRepairProcessor)

        # Assert that ToolCallRepairProcessor received the correct IToolCallRepairService
        expected_repair_service = provider.get_required_service(IToolCallRepairService)  # type: ignore[type-abstract]
        assert tool_call_processor.tool_call_repair_service is expected_repair_service

        # Assert that unified pipeline is configured
        assert hasattr(response_processor, "_unified_pipeline")
        assert response_processor._unified_pipeline is not None

    def test_tool_call_reactor_subsystem_registration(self) -> None:
        """Test that all tool call reactor subsystem components are registered as singletons."""
        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        # Import all subsystem components and interfaces
        from src.core.interfaces.replacement_response_factory_interface import (
            IReplacementResponseFactory,
        )
        from src.core.interfaces.tool_arguments_fixup_pipeline_interface import (
            IToolArgumentsFixupPipeline,
        )
        from src.core.interfaces.tool_arguments_parser_interface import (
            IToolArgumentsParser,
        )
        from src.core.interfaces.tool_call_deduplicator_interface import (
            IToolCallDeduplicator,
        )
        from src.core.interfaces.tool_call_extractor_interface import IToolCallExtractor
        from src.core.interfaces.tool_call_normalizer_interface import (
            IToolCallNormalizer,
        )
        from src.core.interfaces.tool_call_reactor_orchestrator_interface import (
            IToolCallReactorOrchestrator,
        )
        from src.core.interfaces.tool_call_stream_context_resolver_interface import (
            IToolCallStreamContextResolver,
        )
        from src.core.services.tool_call_reactor.arguments_fixup_pipeline import (
            ToolArgumentsFixupPipeline,
        )
        from src.core.services.tool_call_reactor.arguments_parser import (
            ToolArgumentsParser,
        )
        from src.core.services.tool_call_reactor.deduplicator import (
            ToolCallDeduplicator,
        )
        from src.core.services.tool_call_reactor.extractor import ToolCallExtractor
        from src.core.services.tool_call_reactor.normalizer import ToolCallNormalizer
        from src.core.services.tool_call_reactor.orchestrator import (
            ToolCallReactorOrchestrator,
        )
        from src.core.services.tool_call_reactor.replacement_response_factory import (
            ReplacementResponseFactory,
        )
        from src.core.services.tool_call_reactor.stream_context_resolver import (
            ToolCallStreamContextResolver,
        )

        # Test IToolCallExtractor / ToolCallExtractor
        extractor1 = provider.get_required_service(IToolCallExtractor)  # type: ignore[type-abstract]
        extractor2 = provider.get_required_service(IToolCallExtractor)  # type: ignore[type-abstract]
        assert isinstance(extractor1, ToolCallExtractor)
        assert extractor1 is extractor2

        # Test IToolCallNormalizer / ToolCallNormalizer
        normalizer1 = provider.get_required_service(IToolCallNormalizer)  # type: ignore[type-abstract]
        normalizer2 = provider.get_required_service(IToolCallNormalizer)  # type: ignore[type-abstract]
        assert isinstance(normalizer1, ToolCallNormalizer)
        assert normalizer1 is normalizer2

        # Test IToolCallDeduplicator / ToolCallDeduplicator
        deduplicator1 = provider.get_required_service(IToolCallDeduplicator)  # type: ignore[type-abstract]
        deduplicator2 = provider.get_required_service(IToolCallDeduplicator)  # type: ignore[type-abstract]
        assert isinstance(deduplicator1, ToolCallDeduplicator)
        assert deduplicator1 is deduplicator2

        # Test IToolArgumentsParser / ToolArgumentsParser
        parser1 = provider.get_required_service(IToolArgumentsParser)  # type: ignore[type-abstract]
        parser2 = provider.get_required_service(IToolArgumentsParser)  # type: ignore[type-abstract]
        assert isinstance(parser1, ToolArgumentsParser)
        assert parser1 is parser2

        # Test IToolArgumentsFixupPipeline / ToolArgumentsFixupPipeline
        fixup1 = provider.get_required_service(IToolArgumentsFixupPipeline)  # type: ignore[type-abstract]
        fixup2 = provider.get_required_service(IToolArgumentsFixupPipeline)  # type: ignore[type-abstract]
        assert isinstance(fixup1, ToolArgumentsFixupPipeline)
        assert fixup1 is fixup2

        # Test IReplacementResponseFactory / ReplacementResponseFactory
        factory1 = provider.get_required_service(IReplacementResponseFactory)  # type: ignore[type-abstract]
        factory2 = provider.get_required_service(IReplacementResponseFactory)  # type: ignore[type-abstract]
        assert isinstance(factory1, ReplacementResponseFactory)
        assert factory1 is factory2

        # Test IToolCallStreamContextResolver / ToolCallStreamContextResolver
        resolver1 = provider.get_required_service(IToolCallStreamContextResolver)  # type: ignore[type-abstract]
        resolver2 = provider.get_required_service(IToolCallStreamContextResolver)  # type: ignore[type-abstract]
        assert isinstance(resolver1, ToolCallStreamContextResolver)
        assert resolver1 is resolver2

        # Test IToolCallReactorOrchestrator / ToolCallReactorOrchestrator
        orchestrator1 = provider.get_required_service(IToolCallReactorOrchestrator)  # type: ignore[type-abstract]
        orchestrator2 = provider.get_required_service(IToolCallReactorOrchestrator)  # type: ignore[type-abstract]
        assert isinstance(orchestrator1, ToolCallReactorOrchestrator)
        assert orchestrator1 is orchestrator2

    def test_tool_call_reactor_feature_registration(self) -> None:
        """Test that ToolCallReactorFeature is registered via MiddlewareApplicationManager."""
        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        from src.core.services.middleware_application_manager import (
            MiddlewareApplicationManager,
        )
        from src.core.services.tool_call_reactor_middleware import (
            ToolCallReactorFeature,
        )

        manager = provider.get_required_service(MiddlewareApplicationManager)
        assert manager is not None

        # Verify ToolCallReactorFeature is in the middleware list
        reactor_features = [
            mw for mw in manager._middleware if isinstance(mw, ToolCallReactorFeature)
        ]
        assert (
            len(reactor_features) == 1
        ), "ToolCallReactorFeature should be registered exactly once"
        assert isinstance(reactor_features[0], ToolCallReactorFeature)

    def test_tool_call_reactor_middleware_legacy_registration(self) -> None:
        """Test that legacy ToolCallReactorMiddleware remains registered for backward compatibility."""
        services = ServiceCollection()
        register_core_services(services)
        provider = services.build_service_provider()

        from src.core.services.tool_call_reactor_middleware import (
            ToolCallReactorMiddleware,
        )

        # Legacy middleware should be resolvable
        middleware = provider.get_service(ToolCallReactorMiddleware)
        assert middleware is not None
        assert isinstance(middleware, ToolCallReactorMiddleware)
