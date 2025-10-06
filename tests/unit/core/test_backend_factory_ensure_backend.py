"""
Tests for BackendFactory.ensure_backend method.

These tests verify the behavior of the BackendFactory.ensure_backend method
with different types of backend configurations.
"""

# Tests for BackendFactory.ensure_backend method - now fixed with selective global mocking
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.core.config.app_config import BackendConfig
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import BackendRegistry


@pytest.fixture
def mock_client() -> httpx.AsyncClient:
    """Create a mock HTTP client."""
    return MagicMock(spec=httpx.AsyncClient)


@pytest.fixture
def mock_backend_registry() -> BackendRegistry:
    """Create a mock backend registry."""
    registry = MagicMock(spec=BackendRegistry)
    mock_backend = MagicMock()
    mock_backend_factory = MagicMock(return_value=mock_backend)
    registry.get_backend_factory.return_value = mock_backend_factory
    return registry


# No custom test class needed anymore


@pytest.fixture
def factory(
    mock_client: httpx.AsyncClient, mock_backend_registry: BackendRegistry
) -> BackendFactory:
    """Create a BackendFactory instance with mock dependencies."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    return BackendFactory(
        mock_client, mock_backend_registry, config, TranslationService()
    )


@pytest.mark.asyncio
async def test_ensure_backend_with_none_config(factory: BackendFactory) -> None:
    """Test ensure_backend with None config."""
    # Arrange
    backend_type = "openai"
    app_config = factory._config
    mock_backend = MagicMock()

    # We need to patch the actual method, not the instance method
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, None)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_with_backend_config(factory: BackendFactory) -> None:
    """Test ensure_backend with a BackendConfig object."""
    # Arrange
    backend_type = "openai"
    app_config = factory._config
    backend_config = BackendConfig(
        api_key=["test-api-key"],
        api_url="https://custom-api.example.com",
        extra={"timeout": 30},
    )
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        assert init_config["api_key"] == "test-api-key"
        assert init_config["api_base_url"] == "https://custom-api.example.com"
        assert init_config["timeout"] == 30
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_test_env_injection(factory: BackendFactory) -> None:
    """Test ensure_backend in test environment with no API key.

    Note: Production code no longer auto-injects test keys for security reasons.
    Tests must explicitly provide API keys if needed.
    """
    # Arrange
    backend_type = "openai"
    app_config = factory._config
    backend_config = BackendConfig()  # No API key
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
        patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "test_something"}),
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        # No automatic test key injection for security - expect None when no key provided
        assert init_config["api_key"] is None
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_anthropic_specific(factory: BackendFactory) -> None:
    """Test ensure_backend with Anthropic-specific configuration."""
    # Arrange
    backend_type = "anthropic"
    app_config = factory._config
    backend_config = BackendConfig(api_key=["anthropic-key"])
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        assert init_config["api_key"] == "anthropic-key"
        assert init_config["key_name"] == "anthropic"
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_openrouter_specific(factory: BackendFactory) -> None:
    """Test ensure_backend with OpenRouter-specific configuration."""
    # Arrange
    backend_type = "openrouter"
    app_config = factory._config
    backend_config = BackendConfig(api_key=["openrouter-key"])
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        assert init_config["api_key"] == "openrouter-key"
        assert init_config["key_name"] == "openrouter"
        assert "openrouter_headers_provider" in init_config
        assert init_config["api_base_url"] == "https://openrouter.ai/api/v1"
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_gemini_specific(factory: BackendFactory) -> None:
    """Test ensure_backend with Gemini-specific configuration."""
    # Arrange
    backend_type = "gemini"
    app_config = factory._config
    backend_config = BackendConfig(api_key=["gemini-key"])
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        assert init_config["api_key"] == "gemini-key"
        assert init_config["key_name"] == "gemini"
        assert (
            init_config["api_base_url"] == "https://generativelanguage.googleapis.com"
        )
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_custom_api_url_not_overridden(
    factory: BackendFactory,
) -> None:
    """Test ensure_backend doesn't override custom API URL with default."""
    # Arrange
    backend_type = "gemini"
    app_config = factory._config
    backend_config = BackendConfig(
        api_key=["gemini-key"], api_url="https://custom-gemini-api.example.com"
    )
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        assert init_config["api_key"] == "gemini-key"
        assert init_config["api_base_url"] == "https://custom-gemini-api.example.com"
        assert result == mock_backend
