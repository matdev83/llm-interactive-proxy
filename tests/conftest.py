import logging  # Added logging
import os
from unittest.mock import AsyncMock, patch # Removed MagicMock

# import httpx  # F401: Removed
import pytest
# from fastapi import FastAPI # F401: Removed
from fastapi.testclient import TestClient
# from starlette.testclient import TestClient  # F811: Removed duplicate/unused

import src.main as app_main
from src.connectors import GeminiBackend, OpenRouterBackend
from src.main import build_app  # Import build_app

# Preserve original Gemini API key for integration tests
ORIG_GEMINI_KEY = os.environ.get("GEMINI_API_KEY_1")

@pytest.fixture(
    scope="session"
)
def configured_app():
    """Fixture to provide a FastAPI app with configured backends for testing."""
    if "OPENROUTER_API_KEY" in os.environ:
        del os.environ["OPENROUTER_API_KEY"]
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    for i in range(1, 21):
        if f"OPENROUTER_API_KEY_{i}" in os.environ:
            del os.environ[f"OPENROUTER_API_KEY_{i}"]
        if f"GEMINI_API_KEY_{i}" in os.environ:
            del os.environ[f"GEMINI_API_KEY_{i}"]

    os.environ["OPENROUTER_API_KEY_1"] = "dummy-openrouter-key-1"
    os.environ["OPENROUTER_API_KEY_2"] = "dummy-openrouter-key-2"
    os.environ["GEMINI_API_KEY"] = "dummy-gemini-key"
    os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"
    os.environ["LLM_BACKEND"] = "openrouter"
    app = build_app()
    yield app
    if "OPENROUTER_API_KEY_1" in os.environ:
        del os.environ["OPENROUTER_API_KEY_1"]
    if "OPENROUTER_API_KEY_2" in os.environ:
        del os.environ["OPENROUTER_API_KEY_2"]
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    if "LLM_INTERACTIVE_PROXY_API_KEY" in os.environ:
        del os.environ["LLM_INTERACTIVE_PROXY_API_KEY"]
    if "LLM_BACKEND" in os.environ:
        del os.environ["LLM_BACKEND"]


@pytest.fixture
def client(configured_app):
    """TestClient for the configured FastAPI app."""
    with TestClient(configured_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        # Ensure backend instances have their available_models populated by mocked list_models
        # This step is crucial if initialize() is not automatically called or if tests need to ensure it.
        # However, build_app() calls initialize, which uses mocked list_models.
        # This explicit setting here acts as a default for tests if they don't further customize.
        if hasattr(c.app.state, "openrouter_backend") and not c.app.state.openrouter_backend.available_models:
            c.app.state.openrouter_backend.available_models = ["m1", "m2"]
        if hasattr(c.app.state, "gemini_backend") and not c.app.state.gemini_backend.available_models:
            c.app.state.gemini_backend.available_models = ["g1"]
        yield c


@pytest.fixture(scope="session")
def configured_interactive_app():
    """Fixture to provide a FastAPI app configured for interactive mode."""
    if "OPENROUTER_API_KEY" in os.environ:
        del os.environ["OPENROUTER_API_KEY"]
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    for i in range(1, 21):
        if f"OPENROUTER_API_KEY_{i}" in os.environ:
            del os.environ[f"OPENROUTER_API_KEY_{i}"]
        if f"GEMINI_API_KEY_{i}" in os.environ:
            del os.environ[f"GEMINI_API_KEY_{i}"]

    os.environ["OPENROUTER_API_KEY_1"] = "dummy-openrouter-key-1"
    os.environ["OPENROUTER_API_KEY_2"] = "dummy-openrouter-key-2"
    os.environ["GEMINI_API_KEY"] = "dummy-gemini-key"
    os.environ["DISABLE_INTERACTIVE_MODE"] = "false"
    os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"
    os.environ["LLM_BACKEND"] = "openrouter"
    app = build_app()
    yield app
    if "OPENROUTER_API_KEY_1" in os.environ:
        del os.environ["OPENROUTER_API_KEY_1"]
    if "OPENROUTER_API_KEY_2" in os.environ:
        del os.environ["OPENROUTER_API_KEY_2"]
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    if "DISABLE_INTERACTIVE_MODE" in os.environ:
        del os.environ["DISABLE_INTERACTIVE_MODE"]
    if "LLM_BACKEND" in os.environ:
        del os.environ["LLM_BACKEND"]
    if "LLM_INTERACTIVE_PROXY_API_KEY" in os.environ:
        del os.environ["LLM_INTERACTIVE_PROXY_API_KEY"]


@pytest.fixture
def interactive_client(configured_interactive_app):
    """TestClient for the configured FastAPI app in interactive mode."""
    with TestClient(configured_interactive_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        # Similar to client fixture, ensure defaults if not populated by initialize
        if hasattr(c.app.state, "openrouter_backend") and not c.app.state.openrouter_backend.available_models:
            c.app.state.openrouter_backend.available_models = ["m1", "m2"]
        if hasattr(c.app.state, "gemini_backend") and not c.app.state.gemini_backend.available_models:
            c.app.state.gemini_backend.available_models = ["g1"]
        yield c


def pytest_sessionstart(session):
    from unittest.mock import AsyncMock, patch
    from src.main import GeminiBackend, OpenRouterBackend

    # patch.object(
    #     OpenRouterBackend,
    #     "get_available_models",
    #     lambda self: ["mock-openrouter-model-1", "mock-openrouter-model-2"],
    # ).start() # MODIFIED: Commented out
    # patch.object(
    #     GeminiBackend,
    #     "get_available_models",
    #     lambda self: ["mock-gemini-model-1", "mock-gemini-model-2"],
    # ).start() # MODIFIED: Commented out
    patch.object(
        OpenRouterBackend,
        "list_models",
        AsyncMock(return_value={"data": [{"id": "mock-openrouter-model-1"}]}),
    ).start()
    patch.object(
        GeminiBackend,
        "list_models",
        AsyncMock(return_value={"models": [{"name": "mock-gemini-model-1"}]}),
    ).start()


@pytest.fixture(autouse=True)
def ensure_functional_backends():
    if not hasattr(app_main, "functional_backends"):
        app_main.functional_backends = {"openrouter", "gemini"}
    yield


@pytest.fixture(autouse=True)
def apply_functional_backends(client): # client fixture will run first
    client.app.state.functional_backends = {"openrouter", "gemini"}
    yield


@pytest.fixture(autouse=True)
def mock_model_discovery():
    with (
        patch.object(
            OpenRouterBackend,
            "list_models",
            new=AsyncMock(return_value={"data": [{"id": "m1"}, {"id": "m2"}]}),
        ),
        patch.object(
            GeminiBackend,
            "list_models",
            new=AsyncMock(return_value={"models": [{"name": "g1"}]}),
        ),
        # patch.object(
        #     OpenRouterBackend, "get_available_models", return_value=["m1", "m2"]
        # ), # MODIFIED: Commented out
        # patch.object(GeminiBackend, "get_available_models", return_value=["g1"]), # MODIFIED: Commented out
    ):
        yield


def pytest_sessionfinish(session):
    patch.stopall()


@pytest.fixture
def configured_commands_disabled_app():
    if "OPENROUTER_API_KEY" in os.environ:
        del os.environ["OPENROUTER_API_KEY"]
    if "GEMINI_API_KEY" in os.environ:
        del os.environ["GEMINI_API_KEY"]
    for i in range(1, 21):
        if f"OPENROUTER_API_KEY_{i}" in os.environ:
            del os.environ[f"OPENROUTER_API_KEY_{i}"]
        if f"GEMINI_API_KEY_{i}" in os.environ:
            del os.environ[f"GEMINI_API_KEY_{i}"]

    os.environ["OPENROUTER_API_KEY_1"] = "dummy-openrouter-key-1"
    os.environ["GEMINI_API_KEY"] = "dummy-gemini-key"
    os.environ["DISABLE_INTERACTIVE_COMMANDS"] = "true"
    os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"
    os.environ["LLM_BACKEND"] = "openrouter"
    app = build_app()
    yield app
    for var in [
        "OPENROUTER_API_KEY_1",
        "GEMINI_API_KEY",
        "DISABLE_INTERACTIVE_COMMANDS",
        "LLM_BACKEND",
    ]:
        if var in os.environ:
            del os.environ[var]


@pytest.fixture
def commands_disabled_client(configured_commands_disabled_app):
    with TestClient(configured_commands_disabled_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        yield c


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
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger().setLevel(logging.DEBUG)

# Note: Removed duplicate interactive_client fixture definition
