from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import BackendError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.backend_service import BackendService


@pytest.mark.asyncio
async def test_streaming_backend_error_raises_http_error():
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

    backend_config_provider = MagicMock()
    backend_config_provider.apply_backend_config.side_effect = lambda request, *_args, **_kwargs: request  # type: ignore[assignment]
    backend_config_provider.get_backend_config.return_value = None

    model_alias_resolver = MagicMock()
    model_alias_resolver.resolve.side_effect = lambda model: model

    session_service = MagicMock()
    session_service.get_session = AsyncMock(return_value=None)

    service = BackendService(
        factory=MagicMock(),
        rate_limiter=MagicMock(),
        config=MagicMock(),
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

    with pytest.raises(BackendError) as exc_info:
        await service.call_completion(request, stream=True, allow_failover=True)

    assert exc_info.value.status_code == 500
