import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.main import app
from src.session_manager import SessionManager

@pytest.fixture
def client():
    with TestClient(app) as c:
        c.app.state.session_manager = SessionManager(ttl_seconds=0)  # expire immediately for TTL test
        yield c

def test_session_header_and_persistence(client: TestClient):
    client.app.state.session_manager = SessionManager(ttl_seconds=1000)  # override TTL for this test
    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        session = client.app.state.session_manager.get_session(None, "test")
        payload = {"model": "m1", "messages": [{"role": "user", "content": "!/set(model=foo)"}]}
        resp1 = client.post("/v1/chat/completions", json=payload, headers={"X-Session-ID": session.session_id})
        assert resp1.status_code == 200
        assert resp1.headers["X-Session-ID"] == session.session_id
        assert client.app.state.session_manager.sessions[session.session_id].proxy_state.override_model == "foo"

        payload2 = {"model": "m1", "messages": [{"role": "user", "content": "hi"}]}
        resp2 = client.post("/v1/chat/completions", json=payload2, headers={"X-Session-ID": session.session_id})
        assert resp2.status_code == 200
        assert resp2.headers["X-Session-ID"] == session.session_id
        assert mock_method.call_count == 1

def test_session_ttl_expiry(client: TestClient):
    with patch.object(app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.return_value = {"choices": [{"message": {"content": "ok"}}]}
        session = client.app.state.session_manager.get_session(None, "test")
        payload = {"model": "m1", "messages": [{"role": "user", "content": "hi"}]}
        resp1 = client.post("/v1/chat/completions", json=payload, headers={"X-Session-ID": session.session_id})
        first_id = resp1.headers["X-Session-ID"]

        resp2 = client.post("/v1/chat/completions", json=payload, headers={"X-Session-ID": session.session_id})
        assert resp2.headers["X-Session-ID"] != first_id

