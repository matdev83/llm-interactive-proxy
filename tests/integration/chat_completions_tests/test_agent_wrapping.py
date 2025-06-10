from unittest.mock import AsyncMock, patch

# import pytest # F401: Removed


def test_cline_command_wrapping(client):
    # Prime session with first message to detect agent
    with patch.object(
        client.app.state.openrouter_backend, "chat_completions", new_callable=AsyncMock
    ) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        payload = {
            "model": "m",
            "messages": [{"role": "system", "content": "You are Cline, use tools"}],
        }
        client.post("/v1/chat/completions", json=payload)

    session = client.app.state.session_manager.get_session("default")
    assert session.agent == "cline"

    payload = {"model": "m", "messages": [{"role": "user", "content": "!/hello"}]}
    resp = client.post("/v1/chat/completions", json=payload)
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    assert data["choices"][0]["message"]["content"].startswith("[Proxy Result")
