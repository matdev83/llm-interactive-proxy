"""Phase 4: canonical post-backend path; split-handler types retired from manager/DI."""

from __future__ import annotations

import inspect
from typing import cast

from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.services.migration_gate_service import MigrationGateService


def test_backend_request_manager_init_does_not_accept_split_handler_parameters() -> (
    None
):
    """Orchestration must not take separate streaming/non-streaming handler parameters."""
    params = inspect.signature(BackendRequestManager.__init__).parameters
    assert "non_streaming_handler" not in params
    assert "streaming_handler" not in params
    assert "post_backend_response_coordinator" in params


def test_canonical_post_backend_wiring_after_core_di() -> None:
    """Concrete handlers + coordinator resolve; IBackendRequestManager still resolves."""
    from unittest.mock import MagicMock

    from src.core.config.app_config import AppConfig
    from src.core.di.container import ServiceCollection
    from src.core.di.registrations import core
    from src.core.interfaces.backend_request_manager_interface import (
        IBackendRequestManager,
    )
    from src.core.interfaces.backend_service_interface import IBackendService
    from src.core.interfaces.quality_verifier_service_interface import (
        IQualityVerifierServiceFactory,
    )
    from src.core.interfaces.response_processor_interface import IResponseProcessor
    from src.core.interfaces.wire_capture_interface import IWireCapture
    from src.core.services.backend_request_manager.streaming_response_handler import (
        BackendStreamingResponseHandler,
    )
    from src.core.services.backend_service import BackendService
    from src.core.services.post_backend_response_coordinator import (
        PostBackendResponseCoordinator,
    )

    services = ServiceCollection()
    config = AppConfig.model_validate(
        {
            "session": {"tool_call_reactor": {"enabled": True}},
            "empty_response": {"enabled": True, "max_retries": 1},
        }
    )
    services.add_instance(IBackendService, MagicMock(spec=BackendService))
    services.add_instance(IResponseProcessor, MagicMock())
    services.add_instance(IWireCapture, MagicMock())
    services.add_instance(IQualityVerifierServiceFactory, MagicMock())

    core.register(services, config)
    provider = services.build_service_provider(run_post_build_hooks=False)

    assert provider.get_required_service(PostBackendResponseCoordinator) is not None
    assert provider.get_required_service(BackendStreamingResponseHandler) is not None

    brm = provider.get_required_service(cast(type, IBackendRequestManager))  # type: ignore[type-abstract]
    assert isinstance(brm, BackendRequestManager)
    gate = provider.get_required_service(MigrationGateService)
    assert brm._migration_gate_service is gate
