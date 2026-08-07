"""Tests for Minimax connector."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.base import LLMBackend
from src.connectors.minimax import MinimaxConnector
from src.core.config.app_config import AppConfig


@pytest.fixture
def mock_client():
    """Create a mock HTTP client."""
    return AsyncMock()


@pytest.fixture
def mock_config():
    """Create a mock AppConfig."""
    return MagicMock(spec=AppConfig)


@pytest.fixture
def mock_translation_service():
    """Create a mock translation service."""
    return MagicMock()


@pytest.fixture
async def minimax_backend(mock_client, mock_config, mock_translation_service):
    """Create a MinimaxConnector instance."""
    mock_translation_service.from_domain_request.side_effect = (
        lambda request, *_args, **_kwargs: {
            "model": getattr(request, "model", None),
            "messages": getattr(request, "messages", []),
            "stream": getattr(request, "stream", False),
        }
    )
    model_response = MagicMock()
    model_response.json.return_value = {
        "data": [
            {
                "id": "abab6.5s",
                "name": "abab6.5s",
            }
        ]
    }
    model_response.raise_for_status = MagicMock()
    mock_client.get.return_value = model_response
    backend = MinimaxConnector(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
    )
    await backend.initialize(api_key="test-key")
    return backend


class TestMinimaxConnector:
    """Test class for MinimaxConnector."""

    async def test_backend_type(self, minimax_backend: MinimaxConnector):
        """Test that backend type is set correctly."""
        assert minimax_backend.backend_type == "minimax"

    async def test_api_base_url(self, minimax_backend: MinimaxConnector):
        """Test that API base URL is set correctly."""
        assert minimax_backend.api_base_url == "https://api.minimax.io/v1"

    async def test_backend_initialization(self, minimax_backend: MinimaxConnector):
        """Test backend initialization with API key."""
        assert minimax_backend.api_key == "test-key"

    async def test_get_headers(self, minimax_backend: MinimaxConnector):
        """Test that headers include Authorization with Bearer token."""
        headers = minimax_backend.get_headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test-key"

    async def test_name_property(self, minimax_backend: MinimaxConnector):
        """Test that name property is set correctly."""
        assert minimax_backend.name == "minimax"

    async def test_inherits_from_llm_backend(self):
        """Test that MinimaxConnector inherits from LLMBackend."""
        assert issubclass(MinimaxConnector, LLMBackend)


class TestMinimaxConnectorInitialization:
    """Test MinimaxConnector initialization scenarios."""

    async def test_initialize_with_api_key(self, mock_client, mock_config):
        """Test initialization with API key."""
        backend = MinimaxConnector(mock_client, mock_config)
        await backend.initialize(api_key="test-api-key")
        assert backend.api_key == "test-api-key"

    async def test_initialize_with_custom_api_base_url(self, mock_client, mock_config):
        """Test initialization with custom API base URL."""
        backend = MinimaxConnector(mock_client, mock_config)
        custom_url = "https://custom.minimax.io/v1"
        await backend.initialize(api_key="test-key", api_base_url=custom_url)
        assert backend.api_base_url == custom_url

    async def test_default_api_base_url(self, mock_client, mock_config):
        """Test that default API base URL is set correctly."""
        backend = MinimaxConnector(mock_client, mock_config)
        assert backend.api_base_url == "https://api.minimax.io/v1"
