import logging
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import src.main as app_main
from src.connectors import GeminiBackend, OpenRouterBackend
from src.main import build_app


@pytest.fixture(scope="session", autouse=True)
def mock_testing_session():
    """Main session-scoped fixture to patch backends and other services."""
    with patch.object(
        OpenRouterBackend,
        "list_models",
        AsyncMock(return_value={"data": [{"id": "openrouter/model-a"}, {"id": "openrouter/model-b"}]}),
    ), patch.object(
        GeminiBackend,
        "list_models",
        AsyncMock(return_value={"models": [{"name": "models/gemini-model-1"}, {"name": "models/gemini-model-2"}]}),
    ), patch.object(
        app_main.GeminiCliDirectConnector,
        "initialize",
        AsyncMock(return_value=None),
    ), patch.object(
        app_main.GeminiCliDirectConnector,
        "get_available_models",
        lambda self: ["gemini-1.5-pro", "gemini-1.5-flash"],
    ):
        yield


@pytest.fixture(scope="session")
def configured_app():
    """Fixture to provide a FastAPI app with configured backends for testing."""
    with patch('src.core.config.load_dotenv'):
        os.environ["OPENROUTER_API_KEY_1"] = "dummy-openrouter-key-1"
        os.environ["OPENROUTER_API_KEY_2"] = "dummy-openrouter-key-2"
        os.environ["GEMINI_API_KEY"] = "dummy-gemini-key"
        os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"
        os.environ["LLM_BACKEND"] = "openrouter"

        app = build_app()
        yield app


@pytest.fixture
def client(configured_app):
    """TestClient for the configured FastAPI app."""
    with TestClient(configured_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        yield c


@pytest.fixture
def mock_gemini_backend(client):
    """Provide a patched Gemini backend instance for tests that expect the fixture.

    The fixture replaces ``client.app.state.gemini_backend`` with a lightweight
    mock exposing *get_available_models* so that existing tests can patch other
    methods (e.g. *chat_completions*) without hitting real network calls.
    """
    from unittest.mock import MagicMock

    backend_mock = MagicMock()
    backend_mock.get_available_models.return_value = [
        "gemini-1.5-pro",
        "gemini-1.5-flash",
    ]

    # Inject the mock into the running FastAPI application so that code under
    # test (and subsequent patches inside test functions) see the replacement.
    client.app.state.gemini_backend = backend_mock
    yield backend_mock


@pytest.fixture(scope="session")
def configured_interactive_app():
    """Fixture to provide a FastAPI app configured for interactive mode."""
    with patch('src.core.config.load_dotenv'):
        os.environ["OPENROUTER_API_KEY_1"] = "dummy-openrouter-key-1"
        os.environ["OPENROUTER_API_KEY_2"] = "dummy-openrouter-key-2"
        os.environ["GEMINI_API_KEY"] = "dummy-gemini-key"
        os.environ["DISABLE_INTERACTIVE_MODE"] = "false"
        os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"
        os.environ["LLM_BACKEND"] = "openrouter"

        app = build_app()
        yield app


@pytest.fixture
def interactive_client(configured_interactive_app):
    """TestClient for the configured FastAPI app in interactive mode."""
    with TestClient(configured_interactive_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        yield c


@pytest.fixture
def configured_commands_disabled_app():
    """Fixture to provide a FastAPI app with commands disabled."""
    with patch('src.core.config.load_dotenv'):
        os.environ["OPENROUTER_API_KEY_1"] = "dummy-openrouter-key-1"
        os.environ["GEMINI_API_KEY"] = "dummy-gemini-key"
        os.environ["DISABLE_INTERACTIVE_COMMANDS"] = "true"
        os.environ["LLM_INTERACTIVE_PROXY_API_KEY"] = "test-proxy-key"
        os.environ["LLM_BACKEND"] = "openrouter"

        app = build_app()
        yield app


@pytest.fixture
def commands_disabled_client(configured_commands_disabled_app):
    """TestClient for the configured FastAPI app with commands disabled."""
    with TestClient(configured_commands_disabled_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        yield c


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Cleans up environment variables before and after each test."""
    with patch('src.core.config.load_dotenv'):
        original_env = os.environ.copy()
        yield
        os.environ.clear()
        os.environ.update(original_env)


@pytest.fixture(autouse=True)
def setup_logging():
    """Sets up logging for tests."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger().setLevel(logging.DEBUG)