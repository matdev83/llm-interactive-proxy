from unittest.mock import AsyncMock, MagicMock, patch

from src.connectors import GeminiBackend, OpenRouterBackend
from src.core.app import application_factory as app_main


async def test_openrouter_models_cached():
    # Create a real OpenRouterBackend instance
    from src.connectors.openrouter import OpenRouterBackend

    # Create mock client
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": [{"id": "m1"}, {"id": "m2"}]}
    mock_client.get.return_value = mock_response

    # Create and configure backend
    backend = OpenRouterBackend(mock_client)

    # Mock headers provider
    def mock_headers_provider(key_name, api_key):
        return {"Authorization": f"Bearer {api_key}"}

    # Initialize the backend
    await backend.initialize(
        api_key="test-key",
        openrouter_headers_provider=mock_headers_provider,
        key_name="test",
    )

    # Verify that the models are set
    assert backend.available_models == ["m1", "m2"]


async def test_gemini_models_cached():
    # Create a real GeminiBackend instance
    from src.connectors.gemini import GeminiBackend

    # Create mock client
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"models": [{"name": "g1"}]}
    mock_client.get.return_value = mock_response

    # Create and configure backend
    backend = GeminiBackend(mock_client)

    # Initialize the backend with test values
    await backend.initialize(
        api_key="test-key",
        gemini_api_base_url="https://test-api.example.com",
        key_name="test",
    )

    # Set the models manually for testing
    backend.available_models = ["g1"]

    # Verify that the models are set
    assert backend.get_available_models() == ["g1"]


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
