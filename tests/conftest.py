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

def _clear_specific_api_key_env_vars():
    """Clears common API key environment variables used in tests."""
    # Clear general keys
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ.pop("GEMINI_API_KEY", None)
    # Clear numbered keys
    for i in range(1, 21):
        os.environ.pop(f"OPENROUTER_API_KEY_{i}", None)
        os.environ.pop(f"GEMINI_API_KEY_{i}", None)

def _set_env_vars(vars_to_set: dict) -> dict:
    """Sets environment variables and returns their original values for teardown."""
    original_values = {}
    for k, v in vars_to_set.items():
        original_values[k] = os.environ.get(k)
        os.environ[k] = v
    return original_values

def _restore_env_vars(original_values: dict):
    """Restores environment variables to their original state."""
    for k, v_orig in original_values.items():
        if v_orig is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v_orig

@pytest.fixture(scope="session")
def configured_app():
    """Fixture to provide a FastAPI app with configured backends for testing."""
    from unittest.mock import patch
    
    with patch('src.core.config.load_dotenv'):
        _clear_specific_api_key_env_vars()

        vars_to_set_for_test = {
            "OPENROUTER_API_KEY_1": "dummy-openrouter-key-1",
            "OPENROUTER_API_KEY_2": "dummy-openrouter-key-2",
            "GEMINI_API_KEY": "dummy-gemini-key",  # Use single key to match test expectations (K:1)
            "LLM_INTERACTIVE_PROXY_API_KEY": "test-proxy-key",
            "LLM_BACKEND": "openrouter",
        }
        original_env = _set_env_vars(vars_to_set_for_test)

        app = build_app()
        yield app

        _restore_env_vars(original_env)


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
    from unittest.mock import patch
    
    with patch('src.core.config.load_dotenv'):
        _clear_specific_api_key_env_vars()

        vars_to_set_for_test = {
            "OPENROUTER_API_KEY_1": "dummy-openrouter-key-1",
            "OPENROUTER_API_KEY_2": "dummy-openrouter-key-2",
            "GEMINI_API_KEY": "dummy-gemini-key",  # Use single key to match test expectations (K:1)
            "DISABLE_INTERACTIVE_MODE": "false",
            "LLM_INTERACTIVE_PROXY_API_KEY": "test-proxy-key",
            "LLM_BACKEND": "openrouter",
        }
        original_env = _set_env_vars(vars_to_set_for_test)

        app = build_app()
        yield app

        _restore_env_vars(original_env)


@pytest.fixture
def interactive_client(configured_interactive_app):
    """TestClient for the configured FastAPI app in interactive mode."""
    with TestClient(configured_interactive_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        # Similar to client fixture, ensure defaults if not populated by initialize
        # Set models to match test expectations: gemini (K:1, M:2), openrouter (K:2, M:3)
        if hasattr(c.app.state, "openrouter_backend") and not c.app.state.openrouter_backend.available_models:
            c.app.state.openrouter_backend.available_models = ["m1", "m2", "m3"]
        if hasattr(c.app.state, "gemini_backend") and not c.app.state.gemini_backend.available_models:
            c.app.state.gemini_backend.available_models = ["g1", "g2"]
        yield c


def pytest_sessionstart(session):
    from unittest.mock import AsyncMock, patch
    from src.main import GeminiBackend, OpenRouterBackend
    
    # Clear environment variables at session start to avoid conflicts
    _clear_specific_api_key_env_vars()

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
            new=AsyncMock(return_value={"data": [{"id": "m1"}, {"id": "m2"}, {"id": "model-a"}]}),
        ),
        patch.object(
            GeminiBackend,
            "list_models",
            new=AsyncMock(return_value={"models": [{"name": "g1"}, {"name": "model-a"}]}),
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
    from unittest.mock import patch
    
    with patch('src.core.config.load_dotenv'):
        _clear_specific_api_key_env_vars()

        vars_to_set_for_test = {
            "OPENROUTER_API_KEY_1": "dummy-openrouter-key-1",
            "GEMINI_API_KEY": "dummy-gemini-key",  # Use single key to match test expectations (K:1)
            "DISABLE_INTERACTIVE_COMMANDS": "true",
            "LLM_INTERACTIVE_PROXY_API_KEY": "test-proxy-key", # Already set by clean_env but good to be explicit
            "LLM_BACKEND": "openrouter",
        }
        original_env = _set_env_vars(vars_to_set_for_test)

        app = build_app()
        yield app

        _restore_env_vars(original_env)
        # Explicitly clear DISABLE_INTERACTIVE_COMMANDS as it's specific to this fixture's purpose
        # and might not be in original_env if not set before.
        os.environ.pop("DISABLE_INTERACTIVE_COMMANDS", None)


@pytest.fixture
def commands_disabled_client(configured_commands_disabled_app):
    with TestClient(configured_commands_disabled_app) as c:
        c.headers.update({"Authorization": "Bearer test-proxy-key"})
        yield c


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    from unittest.mock import patch
    
    # Mock load_dotenv to prevent it from loading the .env file during tests
    with patch('src.core.config.load_dotenv'):
        # Store original values for restoration
        original_values = {}
        
        # Clean up before the test - store originals and set to None
        for i in range(1, 21):
            for base in ["GEMINI_API_KEY", "OPENROUTER_API_KEY"]:
                key = f"{base}_{i}"
                original_values[key] = os.environ.get(key)
                monkeypatch.delenv(key, raising=False)
        
        for base in ["GEMINI_API_KEY", "OPENROUTER_API_KEY", "LLM_BACKEND", "DISABLE_INTERACTIVE_COMMANDS"]:
            original_values[base] = os.environ.get(base)
            monkeypatch.delenv(base, raising=False)
        
        # Set the proxy key if not already set
        if "LLM_INTERACTIVE_PROXY_API_KEY" not in os.environ:
            monkeypatch.setenv("LLM_INTERACTIVE_PROXY_API_KEY", "test-proxy-key")
        
        yield
        
        # Clean up after the test - monkeypatch should handle restoration automatically


@pytest.fixture(autouse=True)
def setup_logging():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logging.getLogger().setLevel(logging.DEBUG)

# Note: Removed duplicate interactive_client fixture definition
