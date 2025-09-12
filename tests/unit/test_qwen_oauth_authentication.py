"""
Enhanced unit tests for Qwen OAuth connector's authentication mechanisms.

These tests focus specifically on the OAuth authentication flow,
token management, refresh mechanisms, and error handling.
"""

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import httpx
import pytest
from fastapi import HTTPException
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.domain.chat import ChatMessage, ChatRequest


class TestQwenOAuthAuthentication:
    """Enhanced tests for Qwen OAuth authentication mechanisms."""

    @pytest.fixture
    def mock_client(self):
        """Mock httpx.AsyncClient."""
        return MagicMock(spec=httpx.AsyncClient)

    @pytest.fixture
    def connector(self, mock_client):
        """QwenOAuthConnector instance with mocked client."""
        from src.core.config.app_config import AppConfig

        config = AppConfig()
        return QwenOAuthConnector(mock_client, config=config)

    @pytest.fixture
    def mock_credentials(self):
        """Mock OAuth credentials with standard fields."""
        return {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": int(time.time() * 1000) + 3600000,  # 1 hour from now
        }

    @pytest.fixture
    def expired_credentials(self):
        """Mock OAuth credentials with an expired token."""
        return {
            "access_token": "expired-access-token",
            "refresh_token": "test-refresh-token",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": int(time.time() * 1000) - 3600000,  # 1 hour ago
        }

    @pytest.mark.asyncio
    async def test_token_refresh_exact_expiry(self, connector):
        """Test token refresh right at expiration boundary."""
        # Set expiry to exactly 30 seconds from now (the refresh buffer time)
        current_time_ms = int(time.time() * 1000)
        expiry_time_ms = current_time_ms + 30000  # 30 seconds from now

        connector._oauth_credentials = {
            "access_token": "about-to-expire-token",
            "refresh_token": "test-refresh-token",
            "expiry_date": expiry_time_ms,
        }

        with patch("time.time", return_value=current_time_ms / 1000):
            # At exactly the buffer boundary, should still refresh
            is_expired = connector._is_token_expired()
            assert is_expired is True

    @pytest.mark.asyncio
    async def test_token_refresh_before_expiry(self, connector):
        """Test token refresh check just before expiration boundary."""
        # Set expiry to 31 seconds from now (just beyond the refresh buffer time)
        current_time_ms = int(time.time() * 1000)
        expiry_time_ms = current_time_ms + 31000  # 31 seconds from now

        connector._oauth_credentials = {
            "access_token": "not-quite-expired-token",
            "refresh_token": "test-refresh-token",
            "expiry_date": expiry_time_ms,
        }

        with patch("time.time", return_value=current_time_ms / 1000):
            # Just before the buffer boundary, should not refresh yet
            is_expired = connector._is_token_expired()
            assert is_expired is False

    @pytest.mark.asyncio
    async def test_token_refresh_flow_success(self, connector, mock_client):
        """Test complete token refresh flow with success."""
        # Set up expired credentials
        connector._oauth_credentials = {
            "access_token": "expired-token",
            "refresh_token": "valid-refresh-token",
            "expiry_date": int(time.time() * 1000) - 60000,  # 1 minute ago
        }

        # Mock successful token refresh response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "token_type": "Bearer",
            "expires_in": 3600,  # 1 hour
            "resource_url": "new.portal.qwen.ai",
        }
        mock_client.post = AsyncMock(return_value=mock_response)

        # Mock the save function
        with patch.object(
            connector, "_save_oauth_credentials", AsyncMock()
        ) as mock_save:
            # Execute refresh
            success = await connector._refresh_token_if_needed()

            # Verify refresh was successful
            assert success is True
            assert connector._oauth_credentials["access_token"] == "new-access-token"
            assert connector._oauth_credentials["refresh_token"] == "new-refresh-token"
            assert connector._oauth_credentials["resource_url"] == "new.portal.qwen.ai"
            assert "expiry_date" in connector._oauth_credentials

            # Verify the API URL was updated
            assert connector.api_base_url == "https://new.portal.qwen.ai/v1"

            # Verify credentials were saved
            mock_save.assert_called_once()

            # Verify correct refresh endpoint was used
            mock_client.post.assert_called_once()
            args, _kwargs = mock_client.post.call_args
            assert args[0] == "https://chat.qwen.ai/api/v1/oauth2/token"

    @pytest.mark.asyncio
    async def test_token_refresh_no_refresh_token(self, connector):
        """Test token refresh when no refresh token is available."""
        # Set up expired credentials without refresh token
        connector._oauth_credentials = {
            "access_token": "expired-token",
            "expiry_date": int(time.time() * 1000) - 60000,  # 1 minute ago
        }

        # Execute refresh
        success = await connector._refresh_token_if_needed()

        # Verify refresh failed
        assert success is False

    @pytest.mark.asyncio
    async def test_token_refresh_http_error(self, connector, mock_client):
        """Test token refresh with HTTP error response."""
        # Set up expired credentials
        connector._oauth_credentials = {
            "access_token": "expired-token",
            "refresh_token": "invalid-refresh-token",
            "expiry_date": int(time.time() * 1000) - 60000,  # 1 minute ago
        }

        # Mock error response from token endpoint
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = json.dumps(
            {"error": "invalid_grant", "error_description": "Invalid refresh token"}
        )
        # Make raise_for_status actually raise an exception
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400 Bad Request", request=MagicMock(), response=mock_response
        )
        mock_client.post = AsyncMock(return_value=mock_response)

        # Execute refresh
        success = await connector._refresh_token_if_needed()

        # Verify refresh failed
        assert success is False

        # Original credentials should remain unchanged
        assert connector._oauth_credentials["access_token"] == "expired-token"
        assert connector._oauth_credentials["refresh_token"] == "invalid-refresh-token"

    @pytest.mark.asyncio
    async def test_token_refresh_network_error(self, connector, mock_client):
        """Test token refresh with network error."""
        # Set up expired credentials
        connector._oauth_credentials = {
            "access_token": "expired-token",
            "refresh_token": "valid-refresh-token",
            "expiry_date": int(time.time() * 1000) - 60000,  # 1 minute ago
        }

        # Mock network error
        mock_client.post = AsyncMock(side_effect=httpx.RequestError("Connection error"))

        # Execute refresh
        success = await connector._refresh_token_if_needed()

        # Verify refresh failed
        assert success is False

    @pytest.mark.asyncio
    async def test_token_refresh_malformed_response(self, connector, mock_client):
        """Test token refresh with malformed JSON response."""
        # Set up expired credentials
        connector._oauth_credentials = {
            "access_token": "expired-token",
            "refresh_token": "valid-refresh-token",
            "expiry_date": int(time.time() * 1000) - 60000,  # 1 minute ago
        }

        # Mock malformed JSON response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json = MagicMock(
            side_effect=json.JSONDecodeError("Invalid JSON", "{malformed", 0)
        )
        mock_client.post = AsyncMock(return_value=mock_response)

        # Execute refresh
        success = await connector._refresh_token_if_needed()

        # Verify refresh failed
        assert success is False

    @pytest.mark.asyncio
    async def test_chat_completion_token_refresh_check(self, connector, mock_client):
        """Test that chat_completions checks and refreshes token first."""
        # Set up expired credentials
        connector._oauth_credentials = {
            "access_token": "expired-token",
            "refresh_token": "valid-refresh-token",
            "expiry_date": int(time.time() * 1000) - 60000,  # 1 minute ago
        }

        # Mock validation to pass and successful refresh
        with (
            patch.object(
                connector, "_validate_runtime_credentials", AsyncMock(return_value=True)
            ),
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=True)
            ) as mock_refresh,
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions", AsyncMock()
            ) as mock_chat,
        ):
            # Create a test request
            request = ChatRequest(
                model="qwen3-coder-plus",
                messages=[ChatMessage(role="user", content="Test")],
                stream=False,
            )

            # Call the method
            await connector.chat_completions(
                request_data=request,
                processed_messages=[{"role": "user", "content": "Test"}],
                effective_model="qwen3-coder-plus",
            )

            # Verify token refresh was checked
            mock_refresh.assert_called_once()

            # Verify parent method was called (since refresh succeeded)
            mock_chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_completion_token_refresh_failure(self, connector):
        """Test chat_completions when token refresh fails."""
        # Mock validation to pass and refresh to fail
        with (
            patch.object(
                connector, "_validate_runtime_credentials", AsyncMock(return_value=True)
            ),
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=False)
            ),
        ):
            # Create a test request
            request = ChatRequest(
                model="qwen3-coder-plus",
                messages=[ChatMessage(role="user", content="Test")],
                stream=False,
            )

            # Call the method, should raise exception
            with pytest.raises(HTTPException) as exc_info:
                await connector.chat_completions(
                    request_data=request,
                    processed_messages=[{"role": "user", "content": "Test"}],
                    effective_model="qwen3-coder-plus",
                )

            # Verify the exception details
            assert exc_info.value.status_code == 401
            assert "Failed to refresh Qwen OAuth token" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_credential_persistence(self, connector, mock_credentials):
        """Test persisting credentials to file system."""
        connector._oauth_credentials = mock_credentials

        with (
            patch("pathlib.Path.home") as mock_home,
            patch("pathlib.Path.mkdir") as mock_mkdir,
            patch("builtins.open", mock_open()) as mock_file,
        ):
            mock_home.return_value = Path("/mock/home")

            # Save credentials
            test_credentials = {
                "access_token": "test-access-token",
                "refresh_token": "test-refresh-token",
                "token_type": "Bearer",
                "resource_url": "portal.qwen.ai",
                "expiry_date": int(time.time() * 1000) + 3600000,  # 1 hour from now
            }
            await connector._save_oauth_credentials(test_credentials)

            # Verify the directory was created
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

            # Verify the file was opened for writing
            mock_file.assert_called_once_with(
                Path("/mock/home/.qwen/oauth_creds.json"), "w", encoding="utf-8"
            )

            # Verify the file was written to
            handle = mock_file()
            assert handle.write.called

            # Reconstruct written data from multiple write calls
            written_data = "".join(call.args[0] for call in handle.write.mock_calls)

            # Parse the JSON and verify contents
            saved_creds = json.loads(written_data)
            assert saved_creds["access_token"] == mock_credentials["access_token"]
            assert saved_creds["refresh_token"] == mock_credentials["refresh_token"]
            assert saved_creds["resource_url"] == mock_credentials["resource_url"]

    @pytest.mark.asyncio
    async def test_credential_persistence_error(self, connector, mock_credentials):
        """Test error handling during credential persistence."""
        connector._oauth_credentials = mock_credentials

        with (
            patch("pathlib.Path.home") as mock_home,
            patch(
                "pathlib.Path.mkdir", side_effect=PermissionError("Permission denied")
            ),
        ):
            mock_home.return_value = Path("/mock/home")

            # Save credentials - should not raise an exception
            test_credentials = {
                "access_token": "test-access-token",
                "refresh_token": "test-refresh-token",
                "token_type": "Bearer",
                "resource_url": "portal.qwen.ai",
                "expiry_date": int(time.time() * 1000) + 3600000,  # 1 hour from now
            }
            await connector._save_oauth_credentials(test_credentials)

            # Function should gracefully handle the error and continue

    @pytest.mark.asyncio
    async def test_credential_loading_success(self, connector, mock_credentials):
        """Test successful loading of credentials from file."""
        with (
            patch("pathlib.Path.home") as mock_home,
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(mock_credentials))),
        ):
            mock_home.return_value = Path("/mock/home")

            # Load credentials
            success = await connector._load_oauth_credentials()

            # Verify success
            assert success is True
            assert (
                connector._oauth_credentials["access_token"]
                == mock_credentials["access_token"]
            )
            assert (
                connector._oauth_credentials["refresh_token"]
                == mock_credentials["refresh_token"]
            )
            assert (
                connector._oauth_credentials["resource_url"]
                == mock_credentials["resource_url"]
            )

            # Verify API URL is set from resource_url
            assert connector.api_base_url == "https://portal.qwen.ai/v1"

    @pytest.mark.asyncio
    async def test_credential_loading_file_not_found(self, connector):
        """Test loading credentials when file doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            # Try to load credentials
            success = await connector._load_oauth_credentials()

            # Verify failure
            assert success is False
            assert connector._oauth_credentials is None

    @pytest.mark.asyncio
    async def test_credential_loading_permission_error(self, connector):
        """Test loading credentials with permission error."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", side_effect=PermissionError("Permission denied")),
        ):
            # Try to load credentials
            success = await connector._load_oauth_credentials()

            # Verify failure
            assert success is False

    @pytest.mark.asyncio
    async def test_credential_loading_malformed_json(self, connector):
        """Test loading credentials with malformed JSON."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="{ invalid json")),
        ):
            # Try to load credentials
            success = await connector._load_oauth_credentials()

            # Verify failure
            assert success is False

    @pytest.mark.asyncio
    async def test_credential_loading_missing_access_token(self, connector):
        """Test loading credentials with missing access token."""
        incomplete_creds = {
            "refresh_token": "test-refresh-token",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
        }

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(incomplete_creds))),
        ):
            # Try to load credentials
            success = await connector._load_oauth_credentials()

            # Verify failure due to missing access token
            assert success is False

    @pytest.mark.asyncio
    async def test_get_headers_valid_token(self, connector, mock_credentials):
        """Test getting headers with valid token."""
        connector._oauth_credentials = mock_credentials

        # Get headers
        headers = connector.get_headers()

        # Verify headers
        assert headers["Authorization"] == f"Bearer {mock_credentials['access_token']}"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"

    @pytest.mark.asyncio
    async def test_get_headers_no_token(self, connector):
        """Test getting headers with no token."""
        connector._oauth_credentials = None

        # Get headers should raise exception
        with pytest.raises(HTTPException) as exc_info:
            connector.get_headers()

        # Verify exception
        assert exc_info.value.status_code == 401
        assert "No valid Qwen OAuth access token available" in str(
            exc_info.value.detail
        )


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v"])
