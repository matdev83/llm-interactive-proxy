import re  # Import re

import httpx  # Import httpx
import pytest
from pytest_httpx import HTTPXMock


@pytest.mark.httpx_mock()
def test_rate_limit_wait_and_retry(client, httpx_mock: HTTPXMock, monkeypatch):
    error_detail = {
        "error": {
            "code": 429,
            "message": "quota exceeded",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "1s",
                }
            ],
        }
    }

    request_count = 0

    def gemini_rate_limit_callback(request):
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            return httpx.Response(429, json=error_detail)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    httpx_mock.add_callback(
        gemini_rate_limit_callback,
        url=re.compile(
            r"https://generativelanguage.googleapis.com/v1beta/models/gemini-1:generateContent.*"
        ),
        method="POST",
        is_reusable=True,
    )

    # Use a command to set the backend to gemini
    set_backend_payload = {
        "model": "some-model",
        "messages": [{"role": "user", "content": "!/set(backend=gemini)"}],
    }
    client.post("/v1/chat/completions", json=set_backend_payload)

    payload = {"model": "gemini-1", "messages": [{"role": "user", "content": "hi"}]}
    monkeypatch.setattr("src.main.parse_retry_delay", lambda d: 0)

    async def fake_sleep(_):
        return None

    monkeypatch.setattr("src.main.asyncio.sleep", fake_sleep)

    r1 = client.post("/v1/chat/completions", json=payload)
    assert r1.status_code == 429
    r2 = client.post("/v1/chat/completions", json=payload)
    assert r2.status_code == 200
    assert request_count == 2
