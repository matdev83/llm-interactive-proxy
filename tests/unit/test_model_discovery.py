import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from src import main as app_main
from src.connectors import OpenRouterBackend, GeminiBackend


def test_openrouter_models_cached(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "KEY")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    response = {"data": [{"id": "m1"}, {"id": "m2"}]}
    with patch.object(OpenRouterBackend, "list_models", new=AsyncMock(return_value=response)) as mock_list:
        app = app_main.build_app()
        with TestClient(app) as client:
            assert client.app.state.openrouter_backend.get_available_models() == ["m1", "m2"]
            mock_list.assert_awaited_once()


def test_gemini_models_cached(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "KEY")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    response = {"models": [{"name": "g1"}]}
    with patch.object(GeminiBackend, "list_models", new=AsyncMock(return_value=response)) as mock_list:
        app = app_main.build_app()
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            assert client.app.state.gemini_backend.get_available_models() == ["g1"]
            mock_list.assert_awaited_once()
