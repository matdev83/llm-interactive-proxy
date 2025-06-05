import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from src.main import app
from src.session import SessionManager

@pytest.fixture
def interactive_client():
    with TestClient(app) as c:
        c.app.state.session_manager = SessionManager(default_interactive_mode=True)  # type: ignore
        yield c

def test_unknown_command_error(interactive_client: TestClient):
    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        payload = {"model": "m", "messages": [{"role": "user", "content": "!/bad()"}]}
        resp = interactive_client.post("/v1/chat/completions", json=payload)
        mock_method.assert_not_called()
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "proxy_cmd_processed"
    assert "unknown command" in data["choices"][0]["message"]["content"].lower()

def test_set_command_confirmation(interactive_client: TestClient):
    mock_backend_response = {"choices": [{"message": {"content": "ok"}}]}
    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = mock_backend_response
        payload = {"model": "m", "messages": [{"role": "user", "content": "hello !/set(model=foo)"}]}
        resp = interactive_client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    content = resp.json()["choices"][0]["message"]["content"]
    assert "model set to foo" in content
    assert "ok" in content

