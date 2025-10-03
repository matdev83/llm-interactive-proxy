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
    from unittest.mock import AsyncMock

    backend = MagicMock()
    backend.chat_completions = AsyncMock(
        return_value=ResponseEnvelope(
            content={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_mock_hello",
                                    "type": "function",
                                    "function": {
                                        "name": "hello",
                                        "arguments": '{"result": "Hello! I\'m the mock command handler."}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            headers={},
        )
    )
    backend.get_available_models = AsyncMock(return_value=["gpt-3.5-turbo", "gpt-4"])
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
    backend.get_available_models = AsyncMock(return_value=["m1", "m2", "model-a"])
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
    backend.get_available_models = AsyncMock(
        return_value=["gemini-pro", "gemini-ultra"]
    )
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
    backend.get_available_models = AsyncMock(return_value=["claude-2", "claude-3-opus"])
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
    backend.get_available_models = AsyncMock(return_value=["qwen-turbo", "qwen-max"])
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
    backend.get_available_models = AsyncMock(
        return_value=["zai-model-1", "zai-model-2"]
    )
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

        def side_effect(name: str, *args: Any, **kwargs: Any) -> MagicMock:
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


def get_backend_instance(app: Any, backend_type: str) -> Any:
    """Helper function to get a backend instance from the test app."""
    # Create a mock backend instance for testing
    mock_backend = MagicMock()
    mock_backend.chat_completions = AsyncMock()
    return mock_backend


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

    # Patch BackendFactory methods at class level to prevent real network calls
    from src.core.services.backend_factory import BackendFactory

    def create_backend_side_effect(
        backend_type: str, api_key: str | None = None, *args: Any, **kwargs: Any
    ) -> MagicMock:
        if backend_type == "openai":
            return mock_openai_backend
        if backend_type == "openrouter":
            return mock_openrouter_backend
        if backend_type == "gemini":
            return mock_gemini_backend
        if backend_type == "anthropic":
            return mock_anthropic_backend
        if backend_type == "qwen-oauth":
            return mock_qwen_oauth_backend
        if backend_type == "zai":
            return mock_zai_backend
        return MagicMock()

    async def ensure_backend_side_effect(
        backend_type: str, app_config: Any, backend_config: Any | None = None
    ) -> MagicMock:
        return create_backend_side_effect(backend_type)

    async def async_noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    with (
        patch.object(
            BackendFactory,
            "create_backend",
            new=MagicMock(side_effect=create_backend_side_effect),
        ),
        patch.object(
            BackendFactory,
            "ensure_backend",
            new=AsyncMock(side_effect=ensure_backend_side_effect),
        ),
        patch.object(
            BackendFactory, "initialize_backend", new=AsyncMock(side_effect=async_noop)
        ),
        TestClient(app) as client,
    ):
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

    # Get the ApplicationStateService from DI and disable commands
    from src.core.interfaces.application_state_interface import IApplicationState

    app_state_service = app.state.service_provider.get_required_service(
        IApplicationState
    )
    app_state_service.set_disable_commands(True)

    with (
        TestClient(app) as client,
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend"
        ) as mock_create_backend,
    ):

        def side_effect(name: str, *args: Any, **kwargs: Any) -> MagicMock:
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
