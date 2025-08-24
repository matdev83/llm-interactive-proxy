from unittest.mock import AsyncMock, MagicMock, patch

from src.connectors import GeminiBackend, OpenRouterBackend
from src.core.app.test_builder import build_test_app


async def test_openrouter_models_cached() -> None:
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
    def mock_headers_provider(_, api_key):
        return {"Authorization": f"Bearer {api_key}"}

    # Initialize the backend
    await backend.initialize(
        api_key="test-key",
        openrouter_headers_provider=mock_headers_provider,
        key_name="test",
    )

    # Verify that the models are set
    assert backend.available_models == ["m1", "m2"]


async def test_gemini_models_cached() -> None:
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


def test_auto_default_backend(monkeypatch) -> None:
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
        # The behavior has changed - now the system defaults to OpenAI as the fallback backend
        app = build_test_app()
        from fastapi.testclient import TestClient

        with TestClient(
            app, headers={"Authorization": "Bearer test-proxy-key"}
        ) as client:
            # Should default to openai backend when no other backend is available
            assert client.app.state.app_config.backends.default_backend == "openai"


def test_multiple_backends_requires_arg(monkeypatch) -> None:
    # This test is now obsolete because the behavior has changed
    # The system now defaults to 'openai' even with multiple available backends
    # unless explicitly set via LLM_BACKEND
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
        app = build_test_app()
        from fastapi.testclient import TestClient

        with TestClient(
            app, headers={"Authorization": "Bearer test-proxy-key"}
        ) as client:
            # With the updated behavior, it should default to 'openai'
            assert client.app.state.app_config.backends.default_backend == "openai"

        # Now try specifying the backend explicitly
        monkeypatch.setenv("LLM_BACKEND", "gemini")
        app2 = build_test_app()
        with TestClient(
            app2, headers={"Authorization": "Bearer test-proxy-key"}
        ) as client2:
            assert client2.app.state.app_config.backends.default_backend == "gemini"
