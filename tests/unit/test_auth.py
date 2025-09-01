# import os # F401: Removed
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app as build_app


@pytest.fixture(scope="function")
def app_auth_enabled(monkeypatch):
    monkeypatch.setenv("LLM_INTERACTIVE_PROXY_API_KEY", "testkey")
    monkeypatch.setenv("DISABLE_AUTH", "false")
    monkeypatch.setenv("LLM_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "a-real-key")
    with patch(
        "src.connectors.OpenRouterBackend.list_models",
        new=AsyncMock(return_value={"data": [{"id": "some-model"}]}),
    ):
        from src.core.config.app_config import AppConfig

        config = AppConfig()
        config.auth.disable_auth = False  # Explicitly ensure auth is enabled
        config.auth.api_keys = ["testkey"]  # Set valid keys

        app = build_app(config=config)

        # Manually add auth middleware with correct keys
        from src.core.security import APIKeyMiddleware

        app.middleware_stack = None  # Reset middleware stack
        app.add_middleware(APIKeyMiddleware, valid_keys=["testkey"])

        yield app


@pytest.fixture(scope="function")
def client_auth_enabled(app_auth_enabled):
    with TestClient(app_auth_enabled) as client:
        yield client


def test_auth_required(client_auth_enabled):
    response = client_auth_enabled.get("/models")  # No authorization header
    assert response.status_code == 401


def test_auth_wrong_key(client_auth_enabled):
    response = client_auth_enabled.get(
        "/models", headers={"Authorization": "Bearer wrongkey"}
    )
    assert response.status_code == 401


def test_disable_auth(monkeypatch):
    # No backend mocking required: models endpoint provides sane fallbacks
    monkeypatch.setenv("DISABLE_AUTH", "true")
    monkeypatch.delenv("LLM_INTERACTIVE_PROXY_API_KEY", raising=False)
    app = build_app()
    with TestClient(app) as client:
        response = client.get("/models")  # No authorization header
        assert response.status_code == 200


def test_disable_auth_no_key_generated(monkeypatch, capsys):
    monkeypatch.setenv("DISABLE_AUTH", "true")
    monkeypatch.delenv("LLM_INTERACTIVE_PROXY_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "a-real-key")
    with patch(
        "src.connectors.OpenRouterBackend.list_models",
        new=AsyncMock(return_value={"data": [{"id": "some-model"}]}),
    ):
        _ = build_app()  # Build app to check for key generation logs
        captured = capsys.readouterr()
        assert "Generated client API key" not in captured.out
        assert "Generated client API key" not in captured.err
