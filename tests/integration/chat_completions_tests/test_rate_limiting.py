import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import HTTPException

from src import main as app_main

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "KEY")
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    test_app = app_main.build_app()
    with TestClient(test_app) as c:
        yield c

def test_rate_limit_memory(client: TestClient):
    error_detail = {
        "error": {
            "code": 429,
            "message": "quota exceeded",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "1s"}
            ],
        }
    }

    async def raise_429(*args, **kwargs):
        raise HTTPException(status_code=429, detail=error_detail)

    with patch.object(client.app.state.gemini_backend, 'chat_completions', new_callable=AsyncMock) as mock_method:
        mock_method.side_effect = raise_429
        payload = {"model": "gemini-1", "messages": [{"role": "user", "content": "hi"}]}
        r1 = client.post("/v1/chat/completions", json=payload)
        assert r1.status_code == 429
        r2 = client.post("/v1/chat/completions", json=payload)
        assert r2.status_code == 429
        assert mock_method.call_count == 1
