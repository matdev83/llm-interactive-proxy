"""
Regression test for Loop Detector Scope.

Ensures that ILoopDetector is registered as Transient to prevent state corruption
across concurrent requests.
"""

from src.core.di.container import ServiceCollection

# Prime the registrations package to avoid circular import issues
# Use the correct import path for the registration helper
from src.core.di.registration_helpers.core_processing import (
    register_request_processing_orchestration,
)
from src.core.interfaces.loop_detector_interface import ILoopDetector


def test_loop_detector_is_transient_regression():
    """
    Regression test for Loop Detector Concurrency Bug.

    Verifies that ILoopDetector is registered as Transient.
    If it were Singleton, concurrent requests would share the same instance
    and reset each other's state, causing data corruption.
    """
    services = ServiceCollection()

    # Register services using the helper we modified
    register_request_processing_orchestration(services)

    provider = services.build_service_provider()

    # Resolve twice
    d1 = provider.get_service(ILoopDetector)
    d2 = provider.get_service(ILoopDetector)

    assert d1 is not None, "ILoopDetector was not registered"
    assert d2 is not None, "ILoopDetector was not registered"

    # Assert they are different instances (Transient)
    assert d1 is not d2, (
        "ILoopDetector must be Transient (different instances) to avoid concurrency bugs. "
        "It appears to be registered as Singleton (same instance)."
    )
