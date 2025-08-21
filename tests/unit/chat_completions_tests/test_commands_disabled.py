from unittest.mock import AsyncMock, patch

import pytest
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.session_service_interface import ISessionService


@pytest.mark.asyncio
async def test_commands_ignored(commands_disabled_client):
    # Configure the mock response using the backend service pattern (like the working tests)
    from src.core.domain.responses import ResponseEnvelope

    mock_response_content = {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}]
    }
    mock_response_envelope = ResponseEnvelope(content=mock_response_content)

    # Get the backend service from the DI container (same pattern as working tests)
    backend_service = (
        commands_disabled_client.app.state.service_provider.get_required_service(
            IBackendService
        )
    )

    # Mock the backend service using the working pattern
    with patch.object(
        backend_service,
        "call_completion",
        new_callable=AsyncMock,
    ) as mock_method:
        mock_method.return_value = mock_response_envelope

        payload = {
            "model": "m",
            "messages": [{"role": "user", "content": "hi !/set(model=openrouter:foo)"}],
        }
        resp = commands_disabled_client.post("/v1/chat/completions", json=payload)

        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "ok"

        # Verify that backend service was called (since commands are disabled)
        mock_method.assert_called_once()

        # Check the call arguments to verify the command was not processed
        call_args = mock_method.call_args
        request = call_args[0][0] if call_args[0] else call_args[1].get("request")

        # The message content should still contain the command since commands are disabled
        assert len(request.messages) == 1
        assert request.messages[0].content == "hi !/set(model=openrouter:foo)"

    session_service = (
        commands_disabled_client.app.state.service_provider.get_required_service(
            ISessionService
        )
    )
    session = await session_service.get_session("default")
    assert session.state.override_model is None
