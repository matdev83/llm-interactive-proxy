from unittest.mock import AsyncMock, patch

# import pytest # F401: Removed


def test_banner_on_first_reply(interactive_client):
    mock_backend_response = {"choices": [{"message": {"content": "backend"}}]}
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        mock_method.return_value = mock_backend_response
        payload = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
        resp = interactive_client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert "Hello, this is" in content
    assert "Session id" in content
    assert "Functional backends:" in content
    assert "openrouter (K:2, M:3)" in content
    assert "gemini (K:1, M:2)" in content
    assert "backend" in content
    mock_method.assert_called_once()


def test_hello_command_returns_banner(interactive_client):
    with patch.object(
        interactive_client.app.state.openrouter_backend,
        "chat_completions",
        new_callable=AsyncMock,
    ) as mock_method:
        payload = {"model": "m", "messages": [{"role": "user", "content": "!/hello"}]}
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    content = data["choices"][0]["message"]["content"]
    assert "Hello, this is" in content
    assert "Functional backends:" in content
    assert "openrouter (K:2, M:3)" in content
    assert "gemini (K:1, M:2)" in content
