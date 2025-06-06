import os
import pytest
import logging # Added logging
from unittest.mock import AsyncMock, patch # Added patch
from src.connectors import OpenRouterBackend, GeminiBackend
from src.main import build_app # Import build_app
from starlette.testclient import TestClient # Import TestClient
import httpx # Added httpx

# Preserve original Gemini API key for integration tests
ORIG_GEMINI_KEY = os.environ.get("GEMINI_API_KEY_1")

# Removed os.environ.pop calls as they interfere with test setup.
# Environment variables will be managed by monkeypatch fixtures.


@pytest.fixture(autouse=True)
def patch_backend_discovery(monkeypatch):
    monkeypatch.setattr(
        OpenRouterBackend,
        "list_models",
        AsyncMock(return_value={"data": [{"id": "model-a"}]}),
    )
    monkeypatch.setattr(
        GeminiBackend,
        "list_models",
        AsyncMock(return_value={"models": [{"name": "model-a"}]}),
    )
    yield

# @pytest.fixture(autouse=True) # Apply to all tests
# def mock_httpx_client(monkeypatch):
#     """Mocks httpx.AsyncClient to prevent actual network calls during tests."""
#     mock_post = AsyncMock(return_value=httpx.Response(200, json={"mock_response": "ok"}))
#     mock_get = AsyncMock(return_value=httpx.Response(200, json={"data": [{"id": "mock-model-a"}], "models": [{"name": "mock-model-b"}]}))

#     monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
#     monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
#     yield


@pytest.fixture(scope="session") # Use session scope for app to avoid rebuilding for every test
def configured_app():
    """Fixture to provide a FastAPI app with configured backends for testing."""
    # Ensure no numbered API keys are present before setting base keys
    if "OPENROUTER_API_KEY" in os.environ: # Delete unnumbered key
        del os.environ["OPENROUTER_API_KEY"]
    if "GEMINI_API_KEY" in os.environ: # Delete unnumbered key
        del os.environ["GEMINI_API_KEY"]
    for i in range(1, 21):
        if f"OPENROUTER_API_KEY_{i}" in os.environ:
            del os.environ[f"OPENROUTER_API_KEY_{i}"]
        if f"GEMINI_API_KEY_{i}" in os.environ:
            del os.environ[f"GEMINI_API_KEY_{i}"]

    # Manually set environment variables for the session-scoped app build
    os.environ["OPENROUTER_API_KEY_1"] = "dummy-openrouter-key-1"
    os.environ["OPENROUTER_API_KEY_2"] = "dummy-openrouter-key-2" # Add a second key
    os.environ["GEMINI_API_KEY"] = "dummy-gemini-key"
    os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"
    os.environ["LLM_BACKEND"] = "openrouter" # Explicitly set a default backend
    # This will call _load_config internally, which will pick up the env vars
    app = build_app()
    yield app
    # Clean up environment variables after the session
    if "OPENROUTER_API_KEY_1" in os.environ:
        del os.environ["OPENROUTER_API_KEY_1"]
    if "OPENROUTER_API_KEY_2" in os.environ: # Clean up the second key
        del os.environ["OPENROUTER_API_KEY_2"]
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    if "LLM_INTERACTIVE_PROXY_API_KEY" in os.environ:
        del os.environ["LLM_INTERACTIVE_PROXY_API_KEY"]
    if "LLM_BACKEND" in os.environ: # Clean up LLM_BACKEND
        del os.environ["LLM_BACKEND"]

@pytest.fixture
def client(configured_app):
    """TestClient for the configured FastAPI app."""
    with TestClient(configured_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        yield c

@pytest.fixture(scope="session")
def configured_interactive_app():
    """Fixture to provide a FastAPI app configured for interactive mode."""
    # Ensure no numbered API keys are present before setting base keys
    if "OPENROUTER_API_KEY" in os.environ: # Delete unnumbered key
        del os.environ["OPENROUTER_API_KEY"]
    if "GEMINI_API_KEY" in os.environ: # Delete unnumbered key
        del os.environ["GEMINI_API_KEY"]
    for i in range(1, 21):
        if f"OPENROUTER_API_KEY_{i}" in os.environ:
            del os.environ[f"OPENROUTER_API_KEY_{i}"]
        if f"GEMINI_API_KEY_{i}" in os.environ:
            del os.environ[f"GEMINI_API_KEY_{i}"]

    # Manually set environment variables for the session-scoped app build
    os.environ["OPENROUTER_API_KEY_1"] = "dummy-openrouter-key-1" # Use numbered key
    os.environ["OPENROUTER_API_KEY_2"] = "dummy-openrouter-key-2" # Add a second key
    os.environ["GEMINI_API_KEY"] = "dummy-gemini-key"
    os.environ["INTERACTIVE_MODE"] = "true"
    os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"
    os.environ["LLM_BACKEND"] = "openrouter" # Explicitly set a default backend
    app = build_app()
    yield app
    # Clean up environment variables after the session
    if "OPENROUTER_API_KEY_1" in os.environ:
        del os.environ["OPENROUTER_API_KEY_1"]
    if "OPENROUTER_API_KEY_2" in os.environ: # Clean up the second key
        del os.environ["OPENROUTER_API_KEY_2"]
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    if "INTERACTIVE_MODE" in os.environ:
        del os.environ["INTERACTIVE_MODE"]
    if "LLM_BACKEND" in os.environ: # Clean up LLM_BACKEND
        del os.environ["LLM_BACKEND"]
    if "LLM_INTERACTIVE_PROXY_API_KEY" in os.environ:
        del os.environ["LLM_INTERACTIVE_PROXY_API_KEY"]

@pytest.fixture
def interactive_client(configured_interactive_app):
    """TestClient for the configured FastAPI app in interactive mode."""
    with TestClient(configured_interactive_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        yield c


# The clean_env fixture is no longer needed for global API keys as they are managed
# within configured_app and configured_interactive_app.
# It remains for LLM_BACKEND and numbered keys if individual tests set them.
@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    yield
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)

@pytest.fixture(autouse=True)
def setup_logging():
    # Ensure logging is configured at DEBUG level for all tests
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    # Set root logger level to DEBUG as well
    logging.getLogger().setLevel(logging.DEBUG)
