"""
Unit tests for Qwen OAuth connector credential handling functionality.

These tests focus on the unique aspects of the QwenOAuthConnector:
- Credential loading and caching
- Token refresh logic
- API base URL handling
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import httpx
import pytest
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.domain.chat import ChatMessage, ChatRequest

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)


class TestQwenOAuthCredentials:
    """Unit tests for credential handling in QwenOAuthConnector."""

    @pytest.fixture
    def mock_client(self):
        """Mock httpx.AsyncClient."""
        return MagicMock(spec=httpx.AsyncClient)

    @pytest.fixture
    def connector(self, mock_client):
        """QwenOAuthConnector instance with mocked client."""
        from src.core.config.app_config import AppConfig

        config = AppConfig()
        connector = QwenOAuthConnector(mock_client, config=config)
        return connector

    @pytest.mark.asyncio
    async def test_load_oauth_credentials(self, connector):
        """Test loading OAuth credentials from file."""
        mock_creds = {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": int(time.time() * 1000) + 3600000,
        }

        # Mock Path.exists and Path.stat
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.stat") as mock_stat,
            patch("builtins.open", mock_open(read_data=json.dumps(mock_creds))),
        ):
            # Mock stat to return a modified time
            mock_stat_result = MagicMock()
            mock_stat_result.st_mtime = 12345.0
            mock_stat.return_value = mock_stat_result

            # Call the method
            result = await connector._load_oauth_credentials()

            # Verify results
            assert result is True
            assert connector._oauth_credentials == mock_creds
            assert connector._last_modified == 12345.0
            assert connector.api_base_url == "https://portal.qwen.ai/v1"

    @pytest.mark.asyncio
    async def test_load_oauth_credentials_file_not_found(self, connector):
        """Test loading OAuth credentials when file doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            result = await connector._load_oauth_credentials()
            assert result is False
            assert connector._oauth_credentials is None

    @pytest.mark.asyncio
    async def test_load_oauth_credentials_invalid_json(self, connector):
        """Test loading OAuth credentials with invalid JSON."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="invalid json")),
        ):
            result = await connector._load_oauth_credentials()
            assert result is False
            assert connector._oauth_credentials is None

    @pytest.mark.asyncio
    async def test_load_oauth_credentials_missing_fields(self, connector):
        """Test loading OAuth credentials with missing required fields."""
        mock_creds = {"some_field": "value"}  # Missing access_token and refresh_token

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(mock_creds))),
        ):
            result = await connector._load_oauth_credentials()
            assert result is False
            # The connector doesn't store invalid credentials

    @pytest.mark.asyncio
    async def test_is_token_expired(self, connector):
        """Test token expiry check."""
        # Test with no credentials
        connector._oauth_credentials = None
        assert connector._is_token_expired() is True

        # Test with no expiry date
        connector._oauth_credentials = {"access_token": "test"}
        assert connector._is_token_expired() is False

        # Test with future expiry date
        connector._oauth_credentials = {
            "expiry_date": int(time.time() * 1000) + 3600000
        }
        assert connector._is_token_expired() is False

        # Test with past expiry date
        connector._oauth_credentials = {"expiry_date": int(time.time() * 1000) - 1000}
        assert connector._is_token_expired() is True

    @pytest.mark.asyncio
    async def test_refresh_token_if_needed_not_expired(self, connector):
        """Test refresh token when not expired."""
        connector._oauth_credentials = {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "expiry_date": int(time.time() * 1000) + 3600000,  # 1 hour in the future
        }

        with patch.object(connector, "_is_token_expired", return_value=False):
            result = await connector._refresh_token_if_needed()
            assert result is True

    @pytest.mark.asyncio
    async def test_refresh_token_if_needed_success(self, connector, mock_client):
        """Test successful token refresh."""
        connector._oauth_credentials = {
            "refresh_token": "test-refresh-token",
        }

        # Mock the response from the token endpoint
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
            "resource_url": "new.portal.qwen.ai",
        }
        mock_client.post.return_value = mock_response

        with (
            patch.object(connector, "_is_token_expired", return_value=True),
            patch.object(
                connector, "_save_oauth_credentials", return_value=None
            ) as mock_save,
        ):
            result = await connector._refresh_token_if_needed()

            # Verify the token was refreshed
            assert result is True
            assert connector._oauth_credentials["access_token"] == "new-access-token"
            assert connector._oauth_credentials["refresh_token"] == "new-refresh-token"
            assert "expiry_date" in connector._oauth_credentials
            assert connector.api_base_url == "https://new.portal.qwen.ai/v1"
            mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_token_if_needed_http_error(self, connector, mock_client):
        """Test token refresh with HTTP error."""
        connector._oauth_credentials = {
            "refresh_token": "test-refresh-token",
        }

        # Mock HTTP error
        mock_client.post.side_effect = httpx.HTTPStatusError(
            "Error", request=MagicMock(), response=MagicMock()
        )

        with patch.object(connector, "_is_token_expired", return_value=True):
            result = await connector._refresh_token_if_needed()
            assert result is False

    @pytest.mark.asyncio
    async def test_refresh_token_if_needed_network_error(self, connector, mock_client):
        """Test token refresh with network error."""
        connector._oauth_credentials = {
            "refresh_token": "test-refresh-token",
        }

        # Mock network error
        mock_client.post.side_effect = httpx.RequestError("Error", request=MagicMock())

        with patch.object(connector, "_is_token_expired", return_value=True):
            result = await connector._refresh_token_if_needed()
            assert result is False

    @pytest.mark.asyncio
    async def test_get_headers(self, connector):
        """Test getting headers with access token."""
        connector._oauth_credentials = {
            "access_token": "test-access-token",
            "token_type": "Bearer",
        }

        headers = connector.get_headers()
        assert headers["Authorization"] == "Bearer test-access-token"
        assert headers["Content-Type"] == "application/json"

    @pytest.mark.asyncio
    async def test_chat_completions_with_token_refresh(self, connector, mock_client):
        """Test chat completion with token refresh."""
        # Set up the connector with expired token
        connector._oauth_credentials = {
            "access_token": "old-token",
            "refresh_token": "test-refresh-token",
            "expiry_date": int(time.time() * 1000) - 1000,  # Expired
        }

        # Mock token refresh response
        mock_refresh_response = MagicMock()
        mock_refresh_response.status_code = 200
        mock_refresh_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }

        # Mock chat completion response
        mock_completion_response = MagicMock()
        mock_completion_response.status_code = 200
        mock_completion_response.json.return_value = {
            "id": "test-id",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Test response"},
                    "finish_reason": "stop",
                }
            ],
        }
        mock_completion_response.headers = {"content-type": "application/json"}

        # Set up the mock client to return different responses for different calls
        mock_client.post.side_effect = [mock_refresh_response, mock_completion_response]

        # Create a simple request
        test_message = ChatMessage(role="user", content="Hello")
        request_data = ChatRequest(
            model="qwen3-coder-plus",
            messages=[test_message],
            stream=False,
        )

        # Call the method
        with (
            patch.object(
                connector, "_validate_runtime_credentials", AsyncMock(return_value=True)
            ),
            patch.object(connector, "_save_oauth_credentials", return_value=None),
        ):
            await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

        # Verify the token was refreshed and the completion request was made
        assert mock_client.post.call_count == 2
        # First call should be to refresh token
        refresh_call = mock_client.post.call_args_list[0]
        assert "token" in refresh_call[0][0]
        # Second call should be for chat completion
        completion_call = mock_client.post.call_args_list[1]
        assert "chat/completions" in completion_call[0][0]
        # Verify the new token was used
        assert "Authorization" in completion_call[1]["headers"]
        assert "new-access-token" in completion_call[1]["headers"]["Authorization"]
