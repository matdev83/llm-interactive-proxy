from unittest.mock import AsyncMock, patch


def test_commands_ignored(commands_disabled_client):
    mock_response = {"choices": [{"message": {"content": "ok"}}]}
    with patch.object(
        commands_disabled_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        mock_method.return_value = mock_response
        payload = {
            "model": "m",
            "messages": [{"role": "user", "content": "hi !/set(model=openrouter:foo)"}],
        }
        resp = commands_disabled_client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "ok"
    call_args = mock_method.call_args.kwargs
    assert (
        call_args["processed_messages"][0].content == "hi !/set(model=openrouter:foo)"
    )
    session = commands_disabled_client.app.state.session_manager.get_session("default")
    assert session.proxy_state.override_model is None
