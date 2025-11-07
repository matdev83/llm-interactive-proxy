from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from unittest.mock import MagicMock

from src.core.di.container import ServiceCollection
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.loop_detector_interface import (
    ILoopDetector,
    LoopDetectionResult,
)
from src.core.interfaces.response_processor_interface import IResponseProcessor
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.backend_request_manager_service import BackendRequestManager


class RecordingLoopDetector(ILoopDetector):
    """Simple loop detector implementation that records reset calls."""

    def __init__(self) -> None:
        self.reset_count = 0

    def is_enabled(self) -> bool:
        return True

    def process_chunk(self, chunk: str):  # type: ignore[override]
        return None

    def reset(self) -> None:
        self.reset_count += 1

    def get_loop_history(self):  # type: ignore[override]
        return []

    def get_current_state(self):  # type: ignore[override]
        return {}

    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        return LoopDetectionResult(has_loop=False)


def _make_manager_with_factory(
    factory: Callable[[], ILoopDetector],
) -> BackendRequestManager:
    backend_processor = MagicMock(spec=IBackendProcessor)
    response_processor = MagicMock(spec=IResponseProcessor)
    return BackendRequestManager(
        backend_processor=backend_processor,
        response_processor=response_processor,
        loop_detector_factory=factory,
    )


def test_backend_request_manager_uses_injected_loop_detector_factory() -> None:
    """A supplied loop detector factory should be preferred over DI fallback."""

    detector = RecordingLoopDetector()

    manager = _make_manager_with_factory(lambda: detector)

    created = manager._create_loop_detector()

    assert created is detector
    assert detector.reset_count == 1


def test_backend_request_manager_respects_provider_loop_detector() -> None:
    """Factory provided by a scoped provider should create detectors per scope."""

    services = ServiceCollection()

    backend_processor = MagicMock(spec=IBackendProcessor)
    response_processor = MagicMock(spec=IResponseProcessor)
    wire_capture = MagicMock(spec=IWireCapture)

    services.add_instance(cast(type, IBackendProcessor), backend_processor)
    services.add_instance(cast(type, IResponseProcessor), response_processor)
    services.add_instance(cast(type, IWireCapture), wire_capture)

    services.add_transient(
        cast(type, ILoopDetector),
        implementation_factory=lambda _provider: RecordingLoopDetector(),
    )

    def backend_request_manager_factory(provider: Any) -> BackendRequestManager:
        def loop_detector_factory() -> ILoopDetector:
            return provider.get_required_service(cast(type, ILoopDetector))

        return BackendRequestManager(
            backend_processor=provider.get_required_service(
                cast(type, IBackendProcessor)
            ),
            response_processor=provider.get_required_service(
                cast(type, IResponseProcessor)
            ),
            wire_capture=provider.get_required_service(cast(type, IWireCapture)),
            loop_detector_factory=loop_detector_factory,
        )

    services.add_singleton(
        BackendRequestManager, implementation_factory=backend_request_manager_factory
    )

    provider = services.build_service_provider()
    manager = provider.get_required_service(BackendRequestManager)

    detector = manager._create_loop_detector()
    assert isinstance(detector, RecordingLoopDetector)
    assert detector.reset_count == 1

    # Ensure repeated calls create independent detectors
    another = manager._create_loop_detector()
    assert isinstance(another, RecordingLoopDetector)
    assert another is not detector
