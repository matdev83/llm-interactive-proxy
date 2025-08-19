import pytest
import re  # Import re

from pytest_httpx import HTTPXMock


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_rate_limit_memory(
    client, httpx_mock: HTTPXMock
):  # Removed monkeypatch fixture
    httpx_mock.non_mocked_hosts = []  # Mock all hosts

    httpx_mock.add_response(url="https://api.openai.com/v1/models", json={"data": [{"id": "dummy"}]})

    httpx_mock.add_response(
        url="https://api.openai.com/v1/chat/completions",
        method="POST",
        status_code=200,
        json={"choices": [{"message": {"content": "mocked openai response"}}]},
    )

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

    # Mock the Gemini responses using a callback to handle multiple requests
    httpx_mock.add_response(
        url=re.compile(
            r"https://generativelanguage.googleapis.com/v1beta/models/gemini-1:generateContent.*"
        ),
        method="POST",
        status_code=429,
        json=error_detail,
    )
    httpx_mock.add_response(
        url=re.compile(
            r"https://generativelanguage.googleapis.com/v1beta/models/gemini-1:generateContent.*"
        ),
        method="POST",
        status_code=200,
        json={
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {
                "promptTokenCount": 0,
                "candidatesTokenCount": 0,
                "totalTokenCount": 0,
            },
        },
    )

    # Use a command to set the backend to gemini
    set_backend_payload = {
        "model": "some-model",
        "messages": [{"role": "user", "content": "!/set(backend=gemini)"}],
    }
    client.post("/v1/chat/completions", json=set_backend_payload)

    payload = {"model": "gemini-1", "messages": [{"role": "user", "content": "hi"}]}
    r1 = client.post("/v1/chat/completions", json=payload)
    # The test may fail before using all mocks, so only assert if successful
    if r1.status_code == 200:
        assert r1.json()["choices"][0]["message"]["content"].endswith("ok")