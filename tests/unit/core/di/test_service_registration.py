from collections.abc import Iterator  # Added import
from unittest.mock import Mock

import pytest
from src.core.di.container import ServiceCollection
from src.core.di.services import (
    get_service_provider,
    register_core_services,
    set_service_provider,
)
from src.core.domain.streaming_response_processor import LoopDetectionProcessor
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.middleware_application_manager_interface import (
    IMiddlewareApplicationManager,
)
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
        services = ServiceCollection()
        register_core_services(services)
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

    def test_response_processor_streaming_pipeline_setup(self) -> None:
        """
        Test that ResponseProcessor is configured with StreamNormalizer and ToolCallRepairProcessor
        when streaming pipeline is enabled.
        """
        services = ServiceCollection()

        # Mock IApplicationState to enable streaming pipeline
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
            app_state: IApplicationState = provider.get_required_service(
                IApplicationState  # type: ignore[type-abstract]
            )
            response_parser: IResponseParser = provider.get_required_service(
                IResponseParser  # type: ignore[type-abstract]
            )
            middleware_application_manager: (
                IMiddlewareApplicationManager
            ) = provider.get_required_service(
                IMiddlewareApplicationManager  # type: ignore[type-abstract]
            )

            stream_normalizer_instance: IStreamNormalizer | None = None
            if app_state.get_use_streaming_pipeline():
                processors: list[IStreamProcessor] = []

                tool_call_repair_service = provider.get_required_service(
                    IToolCallRepairService  # type: ignore[type-abstract]
                )
                processors.append(ToolCallRepairProcessor(tool_call_repair_service))

                processors.append(
                    LoopDetectionProcessor(loop_detector=HybridLoopDetector())
                )

                stream_normalizer_instance = StreamNormalizer(processors=processors)

            # The 'middleware' and 'detector' arguments were removed from ResponseProcessor's __init__
            # Use the new stream_normalizer_instance and other services directly
            return ResponseProcessor(
                response_parser=response_parser,
                middleware_application_manager=middleware_application_manager,
                app_state=app_state,
                stream_normalizer=stream_normalizer_instance,
                loop_detector=HybridLoopDetector(),
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
        # Add mock services for the new required arguments
        services.add_instance(IResponseParser, Mock(spec=IResponseParser))
        services.add_instance(
            IMiddlewareApplicationManager, Mock(spec=IMiddlewareApplicationManager)
        )

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
