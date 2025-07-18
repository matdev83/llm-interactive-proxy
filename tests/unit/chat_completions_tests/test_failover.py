import pytest
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock

from src.main import build_app


@pytest.mark.httpx_mock()
def test_failover_key_rotation(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "key1")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "key2")
    monkeypatch.setenv("LLM_BACKEND", "openrouter")

    app = build_app()
    with TestClient(app, headers={"Authorization": "Bearer test-proxy-key"}) as client:
        # create route
        payload = {
            "model": "dummy",
            "messages": [
                {"role": "user", "content": "!/create-failover-route(name=r,policy=k)"}
            ],
        }
        client.post("/v1/chat/completions", json=payload)
        payload = {
            "model": "dummy",
            "messages": [
                {"role": "user", "content": "!/route-append(name=r,openrouter:model-x)"}
            ],
        }
        client.post("/v1/chat/completions", json=payload)

        # Mock the OpenRouter responses
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            method="POST",
            status_code=429,
            json={"detail": "limit"},
        )
        httpx_mock.add_response(
            url="https://openrouter.ai/api/v1/chat/completions",
            method="POST",
            status_code=200,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

        payload2 = {"model": "r", "messages": [{"role": "user", "content": "hi"}]}
        resp = client.post("/v1/chat/completions", json=payload2)

        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"].endswith("ok")
        assert len(httpx_mock.get_requests()) == 2


@pytest.mark.httpx_mock()
def test_failover_missing_keys(monkeypatch, httpx_mock: HTTPXMock):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)

    monkeypatch.setenv("GEMINI_API_KEY", "G")
    monkeypatch.setenv("LLM_BACKEND", "gemini")

    from fastapi.testclient import TestClient

    from src import main as app_main

    app = app_main.build_app()
    with TestClient(app, headers={"Authorization": "Bearer test-proxy-key"}) as client:
        client.post(
            "/v1/chat/completions",
            json={
                "model": "d",
                "messages": [
                    {
                        "role": "user",
                        "content": "!/create-failover-route(name=r,policy=m)",
                    }
                ],
            },
        )
        client.post(
            "/v1/chat/completions",
            json={
                "model": "d",
                "messages": [
                    {
                        "role": "user",
                        "content": "!/route-append(name=r,openrouter:model-x)",
                    }
                ],
            },
        )
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "r", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 500
        assert resp.json()["detail"]["error"] == "all backends failed"

