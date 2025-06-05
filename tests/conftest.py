import os
import pytest
from unittest.mock import AsyncMock
import os
from src.connectors import OpenRouterBackend, GeminiBackend
from src.main import build_app, _load_config
from starlette.testclient import TestClient # Import TestClient

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


@pytest.fixture(scope="session")  # Use session scope for app to avoid rebuilding for every test
def configured_app():
    """Fixture to provide a FastAPI app with configured backends for testing."""
    for i in range(1, 21):
        os.environ.pop(f"OPENROUTER_API_KEY_{i}", None)
        os.environ.pop(f"GEMINI_API_KEY_{i}", None)
    cfg = _load_config()
    cfg.update(
        {
            "openrouter_api_keys": {
                "OPENROUTER_API_KEY_1": "dummy-openrouter-key-1",
                "OPENROUTER_API_KEY_2": "dummy-openrouter-key-2",
            },
            "gemini_api_keys": {"GEMINI_API_KEY": "dummy-gemini-key"},
            "backend": "openrouter",
        }
    )
    app = build_app(cfg)
    import src.main as app_main
    app_main.app = app
    yield app

@pytest.fixture
def client(configured_app):
    """TestClient for the configured FastAPI app."""
    with TestClient(configured_app) as c:
        yield c

@pytest.fixture(scope="session")
def configured_interactive_app():
    """Fixture to provide a FastAPI app configured for interactive mode."""
    for i in range(1, 21):
        os.environ.pop(f"OPENROUTER_API_KEY_{i}", None)
        os.environ.pop(f"GEMINI_API_KEY_{i}", None)
    cfg = _load_config()
    cfg.update(
        {
            "openrouter_api_keys": {
                "OPENROUTER_API_KEY_1": "dummy-openrouter-key-1",
                "OPENROUTER_API_KEY_2": "dummy-openrouter-key-2",
            },
            "gemini_api_keys": {"GEMINI_API_KEY": "dummy-gemini-key"},
            "backend": "openrouter",
            "interactive_mode": True,
        }
    )
    app = build_app(cfg)
    import src.main as app_main
    app_main.app = app
    yield app

@pytest.fixture
def interactive_client(configured_interactive_app):
    """TestClient for the configured FastAPI app in interactive mode."""
    with TestClient(configured_interactive_app) as c:
        yield c


# The clean_env fixture is no longer needed for global API keys as they are managed
# within configured_app and configured_interactive_app.
# It remains for LLM_BACKEND and numbered keys if individual tests set them.
@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    yield
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    for i in range(1, 21):
        monkeypatch.delenv(f"GEMINI_API_KEY_{i}", raising=False)
        monkeypatch.delenv(f"OPENROUTER_API_KEY_{i}", raising=False)
