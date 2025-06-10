# import os # F401: Removed
import pytest
from fastapi.testclient import TestClient

from src.main import build_app


@pytest.fixture(scope="function")
def app_auth_enabled(monkeypatch):
    monkeypatch.setenv("LLM_INTERACTIVE_PROXY_API_KEY", "testkey")
    monkeypatch.setenv("DISABLE_AUTH", "false")
    app = build_app()
    return app


@pytest.fixture(scope="function")
def client_auth_enabled(app_auth_enabled):
    with TestClient(app_auth_enabled) as client:
        yield client


def test_auth_required(client_auth_enabled):
    response = client_auth_enabled.get("/models") # No authorization header
    assert response.status_code == 401


def test_auth_wrong_key(client_auth_enabled):
    response = client_auth_enabled.get(
        "/models", headers={"Authorization": "Bearer wrongkey"}
    )
    assert response.status_code == 401


def test_disable_auth(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "true")
    # Key may or may not be present, auth still disabled
    monkeypatch.delenv("LLM_INTERACTIVE_PROXY_API_KEY", raising=False)
    app = build_app()
    with TestClient(app) as client:
        response = client.get("/models") # No authorization header
        assert response.status_code == 200


def test_disable_auth_no_key_generated(monkeypatch, capsys):
    monkeypatch.setenv("DISABLE_AUTH", "true")
    monkeypatch.delenv("LLM_INTERACTIVE_PROXY_API_KEY", raising=False)
    _ = build_app() # Build app to check for key generation logs
    captured = capsys.readouterr()
    assert "Generated client API key" not in captured.out
    assert "Generated client API key" not in captured.err
