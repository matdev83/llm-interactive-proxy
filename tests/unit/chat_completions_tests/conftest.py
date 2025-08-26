from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app as build_app
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendConfig,
    BackendSettings,
    SessionConfig,  # Import SessionConfig
)
from src.core.domain.responses import ResponseEnvelope


@pytest.fixture
def mock_openai_backend() -> MagicMock:
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
def mock_openrouter_backend() -> MagicMock:
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
def mock_gemini_backend() -> MagicMock:
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
def mock_anthropic_backend() -> MagicMock:
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
def mock_qwen_oauth_backend() -> MagicMock:
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
def mock_zai_backend() -> MagicMock:
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
def mock_model_discovery() -> dict[str, list[str]]:
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
    mock_openai_backend: MagicMock,
    mock_openrouter_backend: MagicMock,
    mock_gemini_backend: MagicMock,
    mock_anthropic_backend: MagicMock,
    mock_qwen_oauth_backend: MagicMock,
    mock_zai_backend: MagicMock,
    mock_model_discovery: dict[str, list[str]],
) -> Generator[TestClient, Any, None]:
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

        def side_effect(self, name: str, *args: Any, **kwargs: Any) -> MagicMock:
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
    mock_openai_backend: MagicMock,
    mock_openrouter_backend: MagicMock,
    mock_gemini_backend: MagicMock,
    mock_anthropic_backend: MagicMock,
    mock_qwen_oauth_backend: MagicMock,
    mock_zai_backend: MagicMock,
    mock_model_discovery: dict[str, list[str]],
) -> Generator[TestClient, Any, None]:
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
        session=SessionConfig(default_interactive_mode=True),  # Use SessionConfig
    )
    app = build_app(config)

    # After the app is built, get the CommandRegistry from its service provider
    # and register the mock commands.
    from src.core.services.command_service import CommandRegistry

    from tests.unit.mock_commands import (  # Import necessary mock commands
        MockAnotherCommand,
        MockHelloCommand,
    )

    command_registry = app.state.service_provider.get_required_service(CommandRegistry)
    command_registry.register(MockHelloCommand())
    command_registry.register(MockAnotherCommand())

    with (
        TestClient(app) as client,
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend"
        ) as mock_create_backend,
    ):

        def side_effect(self, name: str, *args: Any, **kwargs: Any) -> MagicMock:
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
    mock_openai_backend: MagicMock,
    mock_openrouter_backend: MagicMock,
    mock_gemini_backend: MagicMock,
    mock_anthropic_backend: MagicMock,
    mock_qwen_oauth_backend: MagicMock,
    mock_zai_backend: MagicMock,
    mock_model_discovery: dict[str, list[str]],
) -> Generator[TestClient, Any, None]:
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
        session=SessionConfig(
            disable_interactive_commands=True
        ),  # Use SessionConfig for commands_enabled
    )
    app = build_app(config)

    # Create a test-specific ApplicationStateService instance to avoid interference from other tests
    from src.core.services.application_state_service import ApplicationStateService

    # Create a fresh instance for this test
    test_app_state_service = ApplicationStateService()
    test_app_state_service.set_state_provider(app.state)
    test_app_state_service.set_disable_commands(True)

    # Replace the DI container's ApplicationStateService instance with our test-specific one
    try:
        app.state.service_provider._descriptors[ApplicationStateService].instance = (
            test_app_state_service
        )
    except Exception:
        # If that doesn't work, try the singleton instances dict
        from contextlib import suppress

        with suppress(Exception):
            app.state.service_provider._singleton_instances[ApplicationStateService] = (
                test_app_state_service
            )

    with (
        TestClient(app) as client,
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend"
        ) as mock_create_backend,
    ):

        def side_effect(self, name: str, *args: Any, **kwargs: Any) -> MagicMock:
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
