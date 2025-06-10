import os

from fastapi.testclient import TestClient

from src.main import build_app


def test_auth_required(monkeypatch):
    monkeypatch.setenv("LLM_INTERACTIVE_PROXY_API_KEY", "secret")
    app = build_app()
    with TestClient(app) as client:
        resp = client.get("/v1/models")
        assert resp.status_code == 401
    monkeypatch.delenv("LLM_INTERACTIVE_PROXY_API_KEY", raising=False)


def test_auth_wrong_key(monkeypatch):
    monkeypatch.setenv("LLM_INTERACTIVE_PROXY_API_KEY", "secret")
    app = build_app()
    with TestClient(app) as client:
        resp = client.get("/v1/models", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401
    monkeypatch.delenv("LLM_INTERACTIVE_PROXY_API_KEY", raising=False)


def test_disable_auth(monkeypatch):
    monkeypatch.setenv("LLM_INTERACTIVE_PROXY_API_KEY", "secret")
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_app()
    with TestClient(app) as client:
        resp = client.get("/v1/models")
        assert resp.status_code != 401
    monkeypatch.delenv("LLM_INTERACTIVE_PROXY_API_KEY", raising=False)
    monkeypatch.delenv("DISABLE_AUTH", raising=False)


def test_disable_auth_no_key_generated(monkeypatch):
    monkeypatch.delenv("LLM_INTERACTIVE_PROXY_API_KEY", raising=False)
    monkeypatch.setenv("DISABLE_AUTH", "true")
    app = build_app()
    assert app.state.client_api_key is None
    with TestClient(app) as client:
        resp = client.get("/v1/models")
        assert resp.status_code == 200
    monkeypatch.delenv("DISABLE_AUTH", raising=False)
