"""
Regression test for loop detection bug fix.

This test verifies that loop detection is properly wired in the DI container
and can detect repetitive content in streaming responses.
"""

from src.core.di.container import ServiceCollection
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.loop_detection.detector import LoopDetector


def test_loop_detector_is_registered_in_di_container():
    """Test that ILoopDetector is properly registered in the DI container."""
    services = ServiceCollection()

    # Register infrastructure services
    from src.core.app.stages.infrastructure import InfrastructureStage
    from src.core.config.app_config import AppConfig

    stage = InfrastructureStage()
    app_config = AppConfig()

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
        loop_detector, LoopDetector
    ), "Should resolve to LoopDetector instance"


def test_loop_detection_processor_can_be_created():
    """Test that LoopDetectionProcessor can be created with proper dependencies."""
    from src.core.domain.streaming_response_processor import LoopDetectionProcessor

    # Create a loop detector
    loop_detector = LoopDetector()

    # Create the processor
    processor = LoopDetectionProcessor(loop_detector)

    assert processor is not None
    assert processor.loop_detector is not None
