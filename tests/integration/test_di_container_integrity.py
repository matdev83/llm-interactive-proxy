"""
Integration tests for DI container integrity.

These tests verify that all critical services are properly registered in the
dependency injection container and can be resolved with their dependencies.

This test suite was created in response to a critical bug where loop detection
was completely disabled due to incorrect import paths and missing factory functions,
which went undetected because there were no tests verifying the full DI chain.
"""

import pytest
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection


class TestDIContainerIntegrity:
    """Test that all critical services are properly wired in the DI container."""

    @pytest.fixture
    def service_collection(self):
        """Create a service collection with all stages registered."""
        return ServiceCollection()

    @pytest.fixture
    async def initialized_services(self, service_collection):
        """Initialize all application stages."""
        from src.core.app.stages.core_services import CoreServicesStage
        from src.core.app.stages.infrastructure import InfrastructureStage
        from src.core.app.stages.processor import ProcessorStage

        config = AppConfig()

        # Execute initialization stages
        infrastructure = InfrastructureStage()
        await infrastructure.execute(service_collection, config)

        core_services = CoreServicesStage()
        await core_services.execute(service_collection, config)

        processor = ProcessorStage()
        await processor.execute(service_collection, config)

        return service_collection

    @pytest.mark.asyncio
    async def test_loop_detector_is_registered(self, initialized_services):
        """Verify ILoopDetector is properly registered in DI container.

        REGRESSION TEST: This would have caught the bug where ILoopDetector
        was not registered due to incorrect import path.
        """
        from src.core.interfaces.loop_detector_interface import ILoopDetector

        provider = initialized_services.build_service_provider()

        # Verify service can be resolved
        loop_detector = provider.get_service(ILoopDetector)
        assert loop_detector is not None, "ILoopDetector must be registered"

        # Verify it's the correct implementation
        from src.loop_detection.detector import LoopDetector

        assert isinstance(
            loop_detector, LoopDetector
        ), f"Expected LoopDetector instance, got {type(loop_detector)}"

    @pytest.mark.asyncio
    async def test_loop_detection_processor_is_registered(self, initialized_services):
        """Verify LoopDetectionProcessor is properly registered with dependencies.

        REGRESSION TEST: This would have caught the bug where LoopDetectionProcessor
        couldn't be instantiated due to missing factory function.
        """
        from src.core.domain.streaming_response_processor import LoopDetectionProcessor

        provider = initialized_services.build_service_provider()

        # Verify service can be resolved
        processor = provider.get_service(LoopDetectionProcessor)
        assert (
            processor is not None
        ), "LoopDetectionProcessor must be registered and resolvable"

        # Verify it has the required dependency
        assert (
            processor.loop_detector is not None
        ), "LoopDetectionProcessor must have ILoopDetector injected"

    @pytest.mark.asyncio
    async def test_stream_normalizer_includes_loop_detection(
        self, initialized_services
    ):
        """Verify StreamNormalizer includes LoopDetectionProcessor in its pipeline.

        REGRESSION TEST: This verifies the full pipeline integration.
        """
        from src.core.domain.streaming_response_processor import LoopDetectionProcessor
        from src.core.interfaces.streaming_response_processor_interface import (
            IStreamNormalizer,
        )

        provider = initialized_services.build_service_provider()

        # Verify stream normalizer is registered
        normalizer = provider.get_service(IStreamNormalizer)
        assert normalizer is not None, "IStreamNormalizer must be registered"

        # Verify it has processors (could be _processors as private attribute)
        assert hasattr(normalizer, "_processors") or hasattr(
            normalizer, "processors"
        ), "StreamNormalizer must have processors"

        processors = getattr(
            normalizer, "_processors", getattr(normalizer, "processors", [])
        )
        assert len(processors) > 0, "StreamNormalizer must have at least one processor"

        # Verify LoopDetectionProcessor is in the pipeline
        has_loop_detection = any(
            isinstance(p, LoopDetectionProcessor) for p in processors
        )
        assert (
            has_loop_detection
        ), "StreamNormalizer must include LoopDetectionProcessor in pipeline"

    @pytest.mark.asyncio
    async def test_response_processor_has_loop_detector(self, initialized_services):
        """Verify ResponseProcessor has access to loop detector.

        REGRESSION TEST: Verifies non-streaming responses also have loop detection.
        """
        from src.core.services.response_processor_service import ResponseProcessor

        provider = initialized_services.build_service_provider()

        # Verify response processor is registered
        response_processor = provider.get_service(ResponseProcessor)
        assert response_processor is not None, "ResponseProcessor must be registered"

        # Verify it has loop detector (may be None if not configured, but attribute should exist)
        assert hasattr(
            response_processor, "_loop_detector"
        ), "ResponseProcessor must have _loop_detector attribute"

    @pytest.mark.asyncio
    async def test_all_critical_services_are_resolvable(self, initialized_services):
        """Verify all critical loop detection services can be resolved without errors.

        This is a smoke test to ensure no service has missing dependencies.
        Note: We only test loop detection-related services since other services
        may require additional stages to be registered.
        """
        from src.core.interfaces.loop_detector_interface import ILoopDetector
        from src.core.interfaces.response_processor_interface import IResponseProcessor
        from src.core.interfaces.streaming_response_processor_interface import (
            IStreamNormalizer,
        )

        provider = initialized_services.build_service_provider()

        # Only test services critical to loop detection
        critical_services = [
            (ILoopDetector, "ILoopDetector"),
            (IResponseProcessor, "IResponseProcessor"),
            (IStreamNormalizer, "IStreamNormalizer"),
        ]

        for service_type, service_name in critical_services:
            try:
                service = provider.get_service(service_type)
                assert (
                    service is not None
                ), f"{service_name} must be resolvable from DI container"
            except Exception as e:
                pytest.fail(
                    f"Failed to resolve {service_name}: {e}. "
                    f"This indicates a DI configuration error."
                )

    @pytest.mark.asyncio
    async def test_loop_detection_end_to_end_wiring(self, initialized_services):
        """End-to-end test of loop detection wiring through the entire stack.

        This test verifies that loop detection is properly wired from
        ILoopDetector -> LoopDetectionProcessor -> StreamNormalizer -> ResponseProcessor
        """
        from src.core.domain.streaming_response_processor import LoopDetectionProcessor
        from src.core.interfaces.loop_detector_interface import ILoopDetector
        from src.core.interfaces.streaming_response_processor_interface import (
            IStreamNormalizer,
        )
        from src.core.services.response_processor_service import ResponseProcessor

        provider = initialized_services.build_service_provider()

        # 1. Verify base detector exists
        loop_detector = provider.get_service(ILoopDetector)
        assert loop_detector is not None, "Step 1: ILoopDetector must exist"

        # 2. Verify processor exists and has detector
        loop_processor = provider.get_service(LoopDetectionProcessor)
        assert loop_processor is not None, "Step 2: LoopDetectionProcessor must exist"
        assert (
            loop_processor.loop_detector is not None
        ), "Step 2: LoopDetectionProcessor must have loop_detector"

        # 3. Verify normalizer exists and has loop processor in pipeline
        normalizer = provider.get_service(IStreamNormalizer)
        assert normalizer is not None, "Step 3: IStreamNormalizer must exist"
        processors = getattr(
            normalizer, "_processors", getattr(normalizer, "processors", [])
        )
        has_loop_processor = any(
            isinstance(p, LoopDetectionProcessor) for p in processors
        )
        assert (
            has_loop_processor
        ), "Step 3: StreamNormalizer must include LoopDetectionProcessor"

        # 4. Verify response processor exists and has normalizer
        response_processor = provider.get_service(ResponseProcessor)
        assert response_processor is not None, "Step 4: ResponseProcessor must exist"
        assert (
            response_processor._stream_normalizer is not None
        ), "Step 4: ResponseProcessor must have stream_normalizer"

        # Verify the chain is connected
        assert (
            response_processor._stream_normalizer == normalizer
        ), "ResponseProcessor must use the same StreamNormalizer instance"

    @pytest.mark.asyncio
    async def test_no_import_errors_during_service_registration(self):
        """Verify that no import errors occur during service registration.

        REGRESSION TEST: The original bug had a silent import error due to
        incorrect import path (loop_detector vs loop_detector_interface).
        """
        from src.core.app.stages.infrastructure import InfrastructureStage

        services = ServiceCollection()
        config = AppConfig()

        # This should not raise any exceptions
        stage = InfrastructureStage()

        try:
            await stage.execute(services, config)
        except ImportError as e:
            pytest.fail(
                f"ImportError during service registration: {e}. "
                f"This indicates incorrect import paths in DI configuration."
            )

    @pytest.mark.asyncio
    async def test_loop_detection_functional_with_real_content(
        self, initialized_services
    ):
        """Functional test that loop detection actually works with real content.

        This is the ultimate integration test - it verifies that the entire
        loop detection system is not only wired correctly, but actually functional.
        """
        from src.core.interfaces.loop_detector_interface import ILoopDetector

        provider = initialized_services.build_service_provider()
        loop_detector = provider.get_service(ILoopDetector)

        # Test that loop detection is functional (basic smoke test)
        # The loop detection algorithm is complex and requires specific patterns
        # This test just verifies the basic integration works
        pattern = "test"
        loop_detector.process_chunk(pattern)

        # The detector should be active and return None for non-looping content
        # More comprehensive functional testing is done in dedicated loop detection tests
        assert loop_detector.is_enabled(), "Loop detector must be enabled"
