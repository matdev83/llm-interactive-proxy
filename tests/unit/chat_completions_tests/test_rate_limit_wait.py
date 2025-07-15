import asyncio
import time

import pytest
from pytest_httpx import HTTPXMock


@pytest.mark.httpx_mock()
def test_wait_for_rate_limited_backends(monkeypatch, client, httpx_mock: HTTPXMock):
    client.post(
        "/v1/chat/completions",
        json={
            "model": "dummy",
            "messages": [
                {"role": "user", "content": "!/create-failover-route(name=r,policy=k)"}
            ],
        },
    )
    client.post(
        "/v1/chat/completions",
        json={
            "model": "dummy",
            "messages": [
                {"role": "user", "content": "!/route-append(name=r,openrouter:m1)"}
            ],
        },
    )

    current = 0.0
    monkeypatch.setattr(time, "time", lambda: current)

    async def fake_sleep(d):
        nonlocal current
        current += d
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    error1 = {
        "error": {
            "code": 429,
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "0.1s",
                }
            ],
        }
    }
    error2 = {
        "error": {
            "code": 429,
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "0.3s",
                }
            ],
        }
    }
    success = {"choices": [{"message": {"content": "ok"}}]}

    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        status_code=429,
        json=error1,
    )
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        status_code=429,
        json=error2,
    )
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        method="POST",
        status_code=200,
        json=success,
    )

    resp = client.post(
        "/v1/chat/completions",
        json={"model": "r", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"].endswith("ok")
    assert current >= 0.1
    assert len(httpx_mock.get_requests()) == 3
