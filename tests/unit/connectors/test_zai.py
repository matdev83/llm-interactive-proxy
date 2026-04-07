from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.zai import ZAIConnector
from src.core.common.exceptions import AuthenticationError
from src.core.domain.chat import ChatRequest


@pytest.fixture
def mock_client():
    """Create a mock HTTP client."""
    return AsyncMock()


@pytest.fixture
def mock_config():
    """Create a mock config."""
    return MagicMock()


@pytest.fixture
async def zai_backend(mock_client, mock_config) -> ZAIConnector:
    """Create a ZAI connector instance."""
    backend = ZAIConnector(client=mock_client, config=mock_config)
    await backend.initialize(api_key="test-key")
    return backend


@pytest.mark.asyncio
async def test_initialize_uses_kwargs_api_key_over_env(zai_backend, mock_config):
    """Explicit kwargs API key should take precedence over environment."""
    original_api_key = zai_backend.api_key

    with patch.dict(
        os.environ,
        {"ZAI_API_KEY": "env-key", "ZAI_API_BASE_URL": "https://override.invalid"},
        clear=False,
    ):
        await zai_backend.initialize(api_key="kwargs-key")

    assert zai_backend.api_key == "kwargs-key"
    assert zai_backend.api_key != original_api_key


@pytest.mark.asyncio
async def test_initialize_falls_back_to_env_when_kwargs_missing(zai_backend, mock_config):
    """Should fall back to ZAI_API_KEY when no kwargs key provided."""
    with patch.dict(
        os.environ,
        {"ZAI_API_KEY": "env-key"},
        clear=False,
    ):
        await zai_backend.initialize()

    assert zai_backend.api_key == "env-key"


@pytest.mark.asyncio
async def test_get_headers_includes_bearer_token(zai_backend):
    """Authorization header should include Bearer token with API key."""
    headers = zai_backend.get_headers(identity=None)

    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_get_headers_raises_when_api_key_not_set(zai_backend):
    """get_headers() should raise when API key is missing."""
    zai_backend.api_key = None

    with pytest.raises(AuthenticationError) as excinfo:
        zai_backend.get_headers(identity=None)

    assert excinfo.value.status_code == 401
    assert "api_key is not set" in str(excinfo.value).lower()
