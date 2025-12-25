from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.failure_handling_config import FailureHandlingConfig
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.backend_model_resolver_interface import ResolvedTarget
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.failure_handling_strategy import DefaultFailureHandlingStrategy

from tests.unit.core.services.backend_flow_test_helper import (
    create_test_backend_completion_flow,
)


@pytest.mark.asyncio
async def test_streaming_429_with_short_retry_after_emits_keepalive_and_retries():
    # Setup mocks
    backend_lifecycle_manager = MagicMock()
    backend_lifecycle_manager.get_disabled_backends.return_value = {}
    backend_lifecycle_manager.get_active_backends.return_value = {}

    mock_backend = MagicMock()
    mock_backend.is_backend_functional.return_value = True
    mock_backend.get_retry_after_remaining.return_value = None

    async def success_stream():
        yield b"data: ok\n\n"

    success_response = StreamingResponseEnvelope(
        content=success_stream(), media_type="text/event-stream", headers={}
    )

    mock_backend.chat_completions = AsyncMock(
        side_effect=[
            BackendError(
                "Rate limited",
                status_code=429,
                details={"retry_after": 1.5},
            ),
            success_response,
        ]
    )

    backend_lifecycle_manager.get_or_create = AsyncMock(return_value=mock_backend)

    backend_config_service = MagicMock()
    backend_config_service.apply_backend_config.side_effect = (
        lambda request, *_args, **_kwargs: request
    )
    backend_config_service.get_backend_config.return_value = None

    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)

    config = AppConfig().model_copy(
        update={
            "failure_handling": FailureHandlingConfig(
                enabled=True,
                total_timeout_budget=3.0,
                max_silent_wait=60.0,
                keepalive_interval=1.0,  # Must be >= 1.0 per validation
                max_failover_hops=5,
                min_retry_wait=0.1,
            )
        }
    )

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
        "config": config,
        "app_state": MagicMock(),
        "failover_coordinator": MagicMock(),
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
    deps["exception_normalizer"].normalize = Mock(side_effect=lambda e, b: e)
    deps["stream_formatting_service"].stream_as_sse_bytes = Mock(
        side_effect=lambda s: s
    )
    deps["usage_tracking_wrapper"].wrap_stream_for_usage = Mock(
        side_effect=lambda s, c, p, t: s
    )
    deps["stream_session_id_resolver"].resolve_stream_session_id.return_value = (
        "test-session"
    )
    deps["planning_phase_manager"].update_counters = AsyncMock()

    # Use real failure handling strategy
    failure_strategy = DefaultFailureHandlingStrategy(config.failure_handling)
    deps["failure_handling_strategy"] = failure_strategy

    flow = create_test_backend_completion_flow(deps)

    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
        extra_body={},
    )

    response = await flow.call_completion(request, stream=True, allow_failover=True)
    assert isinstance(response, StreamingResponseEnvelope)

    chunks = []
    assert response.content is not None
    async for item in response.content:
        chunks.append(item)

    assert any(
        isinstance(c, ProcessedResponse) and bool(c.metadata.get("_keepalive"))
        for c in chunks
    )
    assert any(
        (isinstance(c, bytes | bytearray) and bytes(c) == b"data: ok\n\n")
        or (isinstance(c, ProcessedResponse) and c.content == b"data: ok\n\n")
        for c in chunks
    )
    assert mock_backend.chat_completions.call_count == 2
