from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget

from tests.unit.core.services.backend_flow_test_helper import (
    create_test_backend_completion_flow,
)


@pytest.mark.asyncio
async def test_streaming_backend_error_returns_streaming_envelope():
    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    backend_lifecycle_manager.get_active_backends.return_value = {}

    mock_backend = MagicMock()
    mock_backend.is_backend_functional.return_value = True
    mock_backend.get_retry_after_remaining.return_value = None
    mock_backend.chat_completions = AsyncMock(
        side_effect=BackendError("Internal error encountered.", status_code=500)
    )
    backend_lifecycle_manager.get_or_create = AsyncMock(return_value=mock_backend)

    backend_config_service = MagicMock()
    backend_config_service.apply_backend_config.side_effect = (
        lambda request, *_args, **_kwargs: request
    )
    backend_config_service.get_backend_config.return_value = None

    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)

    config_mock = MagicMock(spec=AppConfig)
    config_mock.backends = MagicMock()
    config_mock.backends.get.return_value = None
    config_mock.identity = None

    # Mock other dependencies
    deps = {
        "backend_model_resolver": MagicMock(),
        "stream_session_id_resolver": MagicMock(),
        "failover_planner": MagicMock(),
        "session_service": session_service,
        "backend_lifecycle_manager": backend_lifecycle_manager,
        "backend_config_service": backend_config_service,
        "reasoning_config_applicator": MagicMock(),
        "uri_parameter_applicator": MagicMock(),
        "stream_formatting_service": MagicMock(),
        "usage_tracking_wrapper": MagicMock(),
        "exception_normalizer": MagicMock(),
        "planning_phase_manager": MagicMock(),
        "backend_factory": MagicMock(),
        "config": config_mock,
        "app_state": MagicMock(),
        "failover_coordinator": MagicMock(),
        "failure_handling_strategy": None,  # No strategy means surface error
    }

    # Defaults
    deps["backend_model_resolver"].resolve_target = AsyncMock(
        return_value=ResolvedTarget(backend="openai", model="test-model", uri_params={})
    )
    deps["backend_model_resolver"].synchronize_request_with_target = Mock(
        side_effect=lambda r, t: r
    )
    deps["reasoning_config_applicator"].apply = Mock(side_effect=lambda r, s: r)
    deps["uri_parameter_applicator"].apply = Mock(side_effect=lambda r, u, b, s: r)

    # Exception normalizer should pass through or wrap the error
    def normalize_side_effect(exc, backend_type):
        if isinstance(exc, BackendError):
            return exc
        return BackendError(str(exc))

    deps["exception_normalizer"].normalize = Mock(side_effect=normalize_side_effect)

    flow = create_test_backend_completion_flow(deps)

    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
        extra_body={},
    )

    result = await flow.call_completion(request, stream=True, allow_failover=True)
    assert result is not None
