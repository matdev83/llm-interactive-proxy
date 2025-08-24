from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app as build_app
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendConfig,
    BackendSettings,
)
from src.core.domain.responses import ResponseEnvelope


@pytest.fixture
def mock_openai_backend():
    """Mock OpenAI backend."""
    backend = MagicMock()
    backend.chat_completions = AsyncMock(
        return_value=ResponseEnvelope(
            content={"choices": [{"message": {"content": "ok"}}]}, headers={}
        )
    )
    backend.get_available_models = lambda: ["gpt-3.5-turbo", "gpt-4"]
    return backend


@pytest.fixture
def mock_openrouter_backend():
    """Mock OpenRouter backend."""
    backend = MagicMock()
    backend.chat_completions = AsyncMock(
        return_value=ResponseEnvelope(
            content={"choices": [{"message": {"content": "ok"}}]}, headers={}
        )
    )
    backend.get_available_models = lambda: ["m1", "m2", "model-a"]
    return backend


@pytest.fixture
def mock_gemini_backend():
    """Mock Gemini backend."""
    backend = MagicMock()
    backend.chat_completions = AsyncMock(
        return_value=ResponseEnvelope(
            content={"choices": [{"message": {"content": "ok"}}]}, headers={}
        )
    )
    backend.get_available_models = lambda: ["gemini-pro", "gemini-ultra"]
    return backend


@pytest.fixture
def mock_anthropic_backend():
    """Mock Anthropic backend."""
    backend = MagicMock()
    backend.chat_completions = AsyncMock(
        return_value=ResponseEnvelope(
            content={"choices": [{"message": {"content": "ok"}}]}, headers={}
        )
    )
    backend.get_available_models = lambda: ["claude-2", "claude-3-opus"]
    return backend


@pytest.fixture
def mock_qwen_oauth_backend():
    """Mock Qwen OAuth backend."""
    backend = MagicMock()
    backend.chat_completions = AsyncMock(
        return_value=ResponseEnvelope(
            content={"choices": [{"message": {"content": "ok"}}]}, headers={}
        )
    )
    backend.get_available_models = lambda: ["qwen-turbo", "qwen-max"]
    return backend


@pytest.fixture
def mock_zai_backend():
    """Mock ZAI backend."""
    backend = MagicMock()
    backend.chat_completions = AsyncMock(
        return_value=ResponseEnvelope(
            content={"choices": [{"message": {"content": "ok"}}]}, headers={}
        )
    )
    backend.get_available_models = lambda: ["zai-model-1", "zai-model-2"]
    return backend


@pytest.fixture
def mock_model_discovery():
    """Mock model discovery."""
    return {
        "openai": ["gpt-3.5-turbo", "gpt-4"],
        "openrouter": ["m1", "m2", "model-a"],
        "gemini": ["gemini-pro", "gemini-ultra"],
        "anthropic": ["claude-2", "claude-3-opus"],
        "qwen-oauth": ["qwen-turbo", "qwen-max"],
        "zai": ["zai-model-1", "zai-model-2"],
    }


@pytest.fixture
def client(
    mock_openai_backend,
    mock_openrouter_backend,
    mock_gemini_backend,
    mock_anthropic_backend,
    mock_qwen_oauth_backend,
    mock_zai_backend,
    mock_model_discovery,
):
    """Create a test client with mocked backends."""
    config = AppConfig(
        auth=AuthConfig(disable_auth=True),
        backends=BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key=["test_key"]),
            openrouter=BackendConfig(api_key=["test_key"]),
            gemini=BackendConfig(api_key=["test_key"]),
            anthropic=BackendConfig(api_key=["test_key"]),
            qwen_oauth=BackendConfig(api_key=["test_key"]),
            zai=BackendConfig(api_key=["test_key"]),
        ),
    )
    app = build_app(config)

    with (
        TestClient(app) as client,
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend"
        ) as mock_create_backend,
    ):

        def side_effect(self, name, *args, **kwargs):
            if name == "openai":
                return mock_openai_backend
            if name == "openrouter":
                return mock_openrouter_backend
            if name == "gemini":
                return mock_gemini_backend
            if name == "anthropic":
                return mock_anthropic_backend
            if name == "qwen-oauth":
                return mock_qwen_oauth_backend
            if name == "zai":
                return mock_zai_backend
            return MagicMock()

        mock_create_backend.side_effect = side_effect

        yield client


@pytest.fixture
def interactive_client(
    mock_openai_backend,
    mock_openrouter_backend,
    mock_gemini_backend,
    mock_anthropic_backend,
    mock_qwen_oauth_backend,
    mock_zai_backend,
    mock_model_discovery,
):
    """Create a test client with interactive mode enabled."""
    config = AppConfig(
        auth=AuthConfig(disable_auth=True),
        backends=BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key=["test_key"]),
            openrouter=BackendConfig(api_key=["test_key"]),
            gemini=BackendConfig(api_key=["test_key"]),
            anthropic=BackendConfig(api_key=["test_key"]),
            qwen_oauth=BackendConfig(api_key=["test_key"]),
            zai=BackendConfig(api_key=["test_key"]),
        ),
        session={"default_interactive_mode": True},
    )
    app = build_app(config)

    with (
        TestClient(app) as client,
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend"
        ) as mock_create_backend,
    ):

        def side_effect(self, name, *args, **kwargs):
            if name == "openai":
                return mock_openai_backend
            if name == "openrouter":
                return mock_openrouter_backend
            if name == "gemini":
                return mock_gemini_backend
            if name == "anthropic":
                return mock_anthropic_backend
            if name == "qwen-oauth":
                return mock_qwen_oauth_backend
            if name == "zai":
                return mock_zai_backend
            return MagicMock()

        mock_create_backend.side_effect = side_effect

        yield client


@pytest.fixture
def commands_disabled_client(
    mock_openai_backend,
    mock_openrouter_backend,
    mock_gemini_backend,
    mock_anthropic_backend,
    mock_qwen_oauth_backend,
    mock_zai_backend,
    mock_model_discovery,
):
    """Create a test client with commands disabled."""
    config = AppConfig(
        auth=AuthConfig(disable_auth=True),
        backends=BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key=["test_key"]),
            openrouter=BackendConfig(api_key=["test_key"]),
            gemini=BackendConfig(api_key=["test_key"]),
            anthropic=BackendConfig(api_key=["test_key"]),
            qwen_oauth=BackendConfig(api_key=["test_key"]),
            zai=BackendConfig(api_key=["test_key"]),
        ),
        commands_enabled=False,
    )
    app = build_app(config)

    # Set disable_commands on the app state to match commands_enabled=False config
    from src.core.services.application_state_service import get_default_application_state
    app_state_service = get_default_application_state()
    app_state_service.set_state_provider(app.state)
    app_state_service.set_disable_commands(True)

    with (
        TestClient(app) as client,
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend"
        ) as mock_create_backend,
    ):

        def side_effect(self, name, *args, **kwargs):
            if name == "openai":
                return mock_openai_backend
            if name == "openrouter":
                return mock_openrouter_backend
            if name == "gemini":
                return mock_gemini_backend
            if name == "anthropic":
                return mock_anthropic_backend
            if name == "qwen-oauth":
                return mock_qwen_oauth_backend
            if name == "zai":
                return mock_zai_backend
            return MagicMock()

        mock_create_backend.side_effect = side_effect

        yield client
