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
    monkeypatch.setenv("LLM_BACKEND", "openrouter") # Add this line
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


def test_auto_default_backend(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "KEY")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    resp = {"data": [{"id": "x"}]}
    with patch.object(OpenRouterBackend, "list_models", new=AsyncMock(return_value=resp)):
        app = app_main.build_app()
        from fastapi.testclient import TestClient
        with TestClient(app) as client:
            assert client.app.state.backend_type == "openrouter"
            assert client.app.state.functional_backends == {"openrouter"}


def test_multiple_backends_requires_arg(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "K1")
    monkeypatch.setenv("GEMINI_API_KEY", "K2")
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    resp_or = {"data": [{"id": "x"}]}
    resp_ge = {"models": [{"name": "g"}]}
    with patch.object(OpenRouterBackend, "list_models", new=AsyncMock(return_value=resp_or)):
        with patch.object(GeminiBackend, "list_models", new=AsyncMock(return_value=resp_ge)):
            app = app_main.build_app()
            from fastapi.testclient import TestClient
            with pytest.raises(ValueError):
                with TestClient(app):
                    pass
