import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch


def test_failover_key_rotation(client):
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

    call_count = [0] # Using a list to hold the mutable call count

    async def side_effect(**kwargs):
        if call_count[0] == 0:
            call_count[0] += 1
            raise HTTPException(status_code=429, detail="limit")
        return {"choices": [{"message": {"content": "ok"}}]}

    with patch.object(client.app.state.openrouter_backend, 'chat_completions', new_callable=AsyncMock) as mock_call:
        mock_call.side_effect = side_effect
        payload2 = {"model": "r", "messages": [{"role": "user", "content": "hi"}]}
        resp = client.post("/v1/chat/completions", json=payload2)

    assert resp.status_code == 200
    assert mock_call.call_count == 2
