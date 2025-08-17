from unittest.mock import AsyncMock, patch

import pytest
from src.core.interfaces.session_service import ISessionService


@patch("src.connectors.openai.OpenAIConnector.chat_completions", new_callable=AsyncMock)
@patch(
    "src.connectors.openrouter.OpenRouterBackend.chat_completions",
    new_callable=AsyncMock,
)
@patch("src.connectors.gemini.GeminiBackend.chat_completions", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_commands_ignored(
    mock_gemini_completions,
    mock_openrouter_completions,
    mock_openai_completions,
    commands_disabled_client,
):
    # Configure the mock response
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    mock_openai_completions.return_value = mock_response
    mock_openrouter_completions.return_value = mock_response
    mock_gemini_completions.return_value = mock_response

    payload = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi !/set(model=openrouter:foo)"}],
    }
    resp = commands_disabled_client.post("/v1/chat/completions", json=payload)

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "ok"

    # Verify that at least one backend was called (since commands are disabled)
    assert (
        mock_openai_completions.called
        or mock_openrouter_completions.called
        or mock_gemini_completions.called
    )

    # Check which backend was actually called and verify its arguments
    if mock_openai_completions.called:
        call_args = mock_openai_completions.call_args.kwargs
    elif mock_openrouter_completions.called:
        call_args = mock_openrouter_completions.call_args.kwargs
    else:
        call_args = mock_gemini_completions.call_args.kwargs

    # processed_messages can be either dict or object with content attribute
    msg = call_args["processed_messages"][0]
    if isinstance(msg, dict):
        assert msg["content"] == "hi !/set(model=openrouter:foo)"
    else:
        assert msg.content == "hi !/set(model=openrouter:foo)"

    session_service = (
        commands_disabled_client.app.state.service_provider.get_required_service(
            ISessionService
        )
    )
    session = await session_service.get_session("default")
    assert session.state.override_model is None
