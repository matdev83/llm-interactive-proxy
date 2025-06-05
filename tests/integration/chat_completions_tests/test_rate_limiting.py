import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

def test_rate_limit_memory(client):
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
