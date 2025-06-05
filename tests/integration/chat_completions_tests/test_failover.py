import pytest
import pytest
from fastapi import HTTPException
from pytest_httpx import HTTPXMock

@pytest.mark.httpx_mock()
def test_failover_key_rotation(client, httpx_mock: HTTPXMock):
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

    # Mock the OpenRouter responses
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        status_code=429,
        json={"detail": "limit"}
    )
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        status_code=200,
        json={"choices": [{"message": {"content": "ok"}}]}
    )

    payload2 = {"model": "r", "messages": [{"role": "user", "content": "hi"}]}
    resp = client.post("/v1/chat/completions", json=payload2)

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"].endswith("ok")
    assert len(httpx_mock.get_requests()) == 2
