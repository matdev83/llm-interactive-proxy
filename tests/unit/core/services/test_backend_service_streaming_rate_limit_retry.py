from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.failure_handling_config import FailureHandlingConfig
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.services.backend_service import BackendService


@pytest.mark.asyncio
async def test_streaming_429_with_short_retry_after_emits_keepalive_and_retries():
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
                details={"retry_after": 0.1},
            ),
            success_response,
        ]
    )

    backend_lifecycle_manager.get_or_create = AsyncMock(return_value=mock_backend)

    backend_config_provider = MagicMock()
    backend_config_provider.apply_backend_config.side_effect = (
        lambda request, *_args, **_kwargs: request  # type: ignore[assignment]
    )
    backend_config_provider.get_backend_config.return_value = None

    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.side_effect = lambda model: model

    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)

    config = AppConfig().model_copy(
        update={
            "failure_handling": FailureHandlingConfig(
                enabled=True,
                total_timeout_budget=2.0,
                max_silent_wait=60.0,
                keepalive_interval=1.0,
                max_failover_hops=5,
                min_retry_wait=0.1,
            )
        }
    )

    service = BackendService(
        factory=MagicMock(),
        rate_limiter=MagicMock(),
        config=config,
        session_service=session_service,
        app_state=MagicMock(),
        backend_config_provider=backend_config_provider,
        failure_handling_strategy=None,
        model_alias_resolver=model_alias_resolver,
        backend_lifecycle_manager=backend_lifecycle_manager,
    )

    service._resolve_backend_and_model = AsyncMock(return_value=("openai", "test-model", {}))  # type: ignore[assignment]

    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=True,
        extra_body={},
    )

    response = await service.call_completion(request, stream=True, allow_failover=True)
    assert isinstance(response, StreamingResponseEnvelope)

    chunks = []
    assert response.content is not None
    async for item in response.content:
        chunks.append(item)

    assert any(
        isinstance(c, bytes | bytearray) and bytes(c).startswith(b":") for c in chunks
    )
    assert any(getattr(c, "content", b"") == b"data: ok\n\n" for c in chunks)
    assert mock_backend.chat_completions.call_count == 2
