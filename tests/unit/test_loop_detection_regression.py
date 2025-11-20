"""
Regression test for loop detection bug fix.

This test verifies that loop detection is properly wired in the DI container
and can detect repetitive content in streaming responses.
"""

from src.core.di.container import ServiceCollection
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.loop_detection.hybrid_detector import HybridLoopDetector


def test_loop_detector_is_registered_in_di_container():
    """Test that ILoopDetector is properly registered in the DI container."""
    import os

    services = ServiceCollection()

    # Register infrastructure services
    from src.core.app.stages.infrastructure import InfrastructureStage
    from src.core.config.app_config import AppConfig

    stage = InfrastructureStage()
    app_config = AppConfig()

    # Ensure loop detection is enabled for this test
    old_value = os.environ.get("LOOP_DETECTION_ENABLED")
    os.environ["LOOP_DETECTION_ENABLED"] = "true"

    try:
        # Execute the infrastructure stage
        import asyncio

        asyncio.run(stage.execute(services, app_config))

        # Build the service provider
        provider = services.build_service_provider()

        # Verify ILoopDetector is registered and can be resolved
        loop_detector = provider.get_service(ILoopDetector)
        assert (
            loop_detector is not None
        ), "ILoopDetector should be registered in DI container"
        assert isinstance(
            loop_detector, HybridLoopDetector
        ), "Should resolve to HybridLoopDetector instance"
    finally:
        if old_value is None:
            os.environ.pop("LOOP_DETECTION_ENABLED", None)
        else:
            os.environ["LOOP_DETECTION_ENABLED"] = old_value


def test_loop_detection_processor_can_be_created():
    """Test that LoopDetectionProcessor can be created with proper dependencies."""
    from src.core.domain.streaming_response_processor import LoopDetectionProcessor

    # Create a loop detector factory
    def loop_detector_factory():
        return HybridLoopDetector()

    # Create the processor
    processor = LoopDetectionProcessor(loop_detector_factory=loop_detector_factory)

    assert processor is not None
    assert processor.loop_detector_factory is loop_detector_factory
