from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from src import main as app_main
from src.connectors import GeminiBackend, OpenRouterBackend


def test_openrouter_models_cached(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "KEY")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    monkeypatch.setenv("LLM_BACKEND", "openrouter")  # Add this line
    response = {"data": [{"id": "m1"}, {"id": "m2"}]}
    with patch.object(
        OpenRouterBackend, "list_models", new=AsyncMock(return_value=response)
    ) as mock_list:
        app = app_main.build_app()
        with TestClient(
            app, headers={"Authorization": "Bearer test-proxy-key"}
        ) as client:
            assert client.app.state.openrouter_backend.get_available_models() == [
                "m1",
                "m2",
            ]
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
    with patch.object(
        GeminiBackend, "list_models", new=AsyncMock(return_value=response)
    ) as mock_list:
        app = app_main.build_app()
        from fastapi.testclient import TestClient

        with TestClient(
            app, headers={"Authorization": "Bearer test-proxy-key"}
        ) as client:
            assert client.app.state.gemini_backend.get_available_models() == ["g1"]
            mock_list.assert_awaited_once()


def test_auto_default_backend(monkeypatch):
    # Test a scenario where only one backend is functional for auto-detection
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"ANTHROPIC_API_KEY_{i}", raising=False)

    # Also ensure Qwen OAuth credentials are not available by mocking the credential loading
    with patch(
        "src.connectors.qwen_oauth.QwenOAuthConnector._load_oauth_credentials",
        return_value=False,
    ):
        # With no API keys set and no OAuth credentials, no backends should be functional
        app = app_main.build_app()
        from fastapi.testclient import TestClient

        with TestClient(
            app, headers={"Authorization": "Bearer test-proxy-key"}
        ) as client:
            # Should have no backend selected
            assert client.app.state.backend_type is None


def test_multiple_backends_requires_arg(monkeypatch):
    # This test is now obsolete because the behavior has changed
    # Now the system automatically selects a default backend when multiple are available
    # We'll test that it selects one of the available backends
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "K1")
    monkeypatch.setenv("GEMINI_API_KEY", "K2")
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    resp_or = {"data": [{"id": "x"}]}
    resp_ge = {"models": [{"name": "g"}]}
    with (
        patch.object(
            OpenRouterBackend, "list_models", new=AsyncMock(return_value=resp_or)
        ),
        patch.object(GeminiBackend, "list_models", new=AsyncMock(return_value=resp_ge)),
        patch(
            "src.connectors.qwen_oauth.QwenOAuthConnector._load_oauth_credentials",
            return_value=False,
        ),
    ):
        app = app_main.build_app()
        from fastapi.testclient import TestClient

        with TestClient(
            app, headers={"Authorization": "Bearer test-proxy-key"}
        ) as client:
            # Should have selected one of the backends
            assert client.app.state.backend_type in ["openrouter", "gemini"]
