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

def _clear_api_env_vars():
    """Clears common API environment variables."""
    if "OPENROUTER_API_KEY" in os.environ:
        del os.environ["OPENROUTER_API_KEY"]
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    for i in range(1, 21): # Max 20 numbered keys as per current logic
        if f"OPENROUTER_API_KEY_{i}" in os.environ:
            del os.environ[f"OPENROUTER_API_KEY_{i}"]
        if f"GEMINI_API_KEY_{i}" in os.environ:
            del os.environ[f"GEMINI_API_KEY_{i}"]

def _setup_env_vars(env_config: dict):
    """Sets environment variables from a dictionary."""
    for key, value in env_config.items():
        os.environ[key] = value

def _cleanup_env_vars(env_config: dict):
    """Cleans up environment variables listed in a dictionary."""
    for key in env_config:
        if key in os.environ:
            del os.environ[key]

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
    _clear_api_env_vars()

    env_vars_to_set = {
        "OPENROUTER_API_KEY_1": "dummy-openrouter-key-1",
        "OPENROUTER_API_KEY_2": "dummy-openrouter-key-2",
        "GEMINI_API_KEY": "dummy-gemini-key",
        "LLM_INTERACTIVE_PROXY_API_KEY": "test-proxy-key",
        "LLM_BACKEND": "openrouter"
    }
    _setup_env_vars(env_vars_to_set)

    app = build_app()
    yield app

    _cleanup_env_vars(env_vars_to_set)

@pytest.fixture
def client(configured_app):
    """TestClient for the configured FastAPI app."""
    with TestClient(configured_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        yield c

@pytest.fixture(scope="session")
def configured_interactive_app():
    """Fixture to provide a FastAPI app configured for interactive mode."""
    _clear_api_env_vars()

    env_vars_to_set = {
        "OPENROUTER_API_KEY_1": "dummy-openrouter-key-1",
        "OPENROUTER_API_KEY_2": "dummy-openrouter-key-2",
        "GEMINI_API_KEY": "dummy-gemini-key",
        "INTERACTIVE_MODE": "true",
        "LLM_INTERACTIVE_PROXY_API_KEY": "test-proxy-key",
        "LLM_BACKEND": "openrouter"
    }
    _setup_env_vars(env_vars_to_set)

    app = build_app()
    yield app

    _cleanup_env_vars(env_vars_to_set)


@pytest.fixture
def interactive_client(configured_interactive_app):
    """TestClient for the configured FastAPI app in interactive mode."""
    with TestClient(configured_interactive_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        yield c


@pytest.fixture
def configured_commands_disabled_app():
    """App with interactive commands disabled."""
    _clear_api_env_vars()

    env_vars_to_set = {
        "OPENROUTER_API_KEY_1": "dummy-openrouter-key-1",
        "GEMINI_API_KEY": "dummy-gemini-key",
        "DISABLE_INTERACTIVE_COMMANDS": "true",
        "LLM_INTERACTIVE_PROXY_API_KEY": "test-proxy-key", # Ensure proxy key is set
        "LLM_BACKEND": "openrouter"
    }
    _setup_env_vars(env_vars_to_set)

    app = build_app()
    yield app

    _cleanup_env_vars(env_vars_to_set)


@pytest.fixture
def commands_disabled_client(configured_commands_disabled_app):
    with TestClient(configured_commands_disabled_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        yield c


# The clean_env fixture is no longer needed for global API keys as they are managed
# within configured_app and configured_interactive_app.
# It remains for LLM_BACKEND and numbered keys if individual tests set them.
@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    if "LLM_INTERACTIVE_PROXY_API_KEY" not in os.environ:
        os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"
    monkeypatch.delenv("DISABLE_INTERACTIVE_COMMANDS", raising=False)
    yield
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.delenv("DISABLE_INTERACTIVE_COMMANDS", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)

@pytest.fixture(autouse=True)
def setup_logging():
    # Ensure logging is configured at DEBUG level for all tests
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    # Set root logger level to DEBUG as well
    logging.getLogger().setLevel(logging.DEBUG)
