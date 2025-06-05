import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch

from src import main as app_main
from src.session import SessionManager


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "K1")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "K2")
    monkeypatch.setenv("LLM_BACKEND", "openrouter")
    test_app = app_main.build_app()
    with TestClient(test_app) as c:
        c.app.state.session_manager = SessionManager()  # type: ignore[attr-defined]
        yield c


def test_failover_key_rotation(client: TestClient):
    # create route
    payload = {
        "model": "dummy",
        "messages": [{"role": "user", "content": "!/create-failover-route(name=r,policy=k)"}],
    }
    client.post("/v1/chat/completions", json=payload)
    payload = {
        "model": "dummy",
        "messages": [{"role": "user", "content": "!/route-append(name=r,openrouter:model-x)"}],
    }
    client.post("/v1/chat/completions", json=payload)

    async def side_effect(**kwargs):
        if side_effect.calls == 0:
            side_effect.calls += 1
            raise HTTPException(status_code=429, detail="limit")
        return {"choices": [{"message": {"content": "ok"}}]}
    side_effect.calls = 0

    with patch.object(client.app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = side_effect
        payload2 = {"model": "r", "messages": [{"role": "user", "content": "hi"}]}
        resp = client.post("/v1/chat/completions", json=payload2)

    assert resp.status_code == 200
    assert mock_call.call_count == 2
