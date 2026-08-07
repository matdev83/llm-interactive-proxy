import asyncio

from src.core.app.stages.infrastructure import InfrastructureStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.loop_detector_interface import ILoopDetector


def test_loop_detector_is_transient():
    """Test that ILoopDetector is transient and not a singleton."""
    services = ServiceCollection()
    stage = InfrastructureStage()
    app_config = AppConfig()

    asyncio.run(stage.execute(services, app_config))

    provider = services.build_service_provider()

    # Resolve ILoopDetector twice
    loop_detector_1 = provider.get_service(ILoopDetector)
    loop_detector_2 = provider.get_service(ILoopDetector)

    assert loop_detector_1 is not None, "ILoopDetector should be registered"
    assert loop_detector_2 is not None, "ILoopDetector should be registered"

    # Assert that the two instances are not the same
    assert loop_detector_1 is not loop_detector_2, "ILoopDetector should be transient"
