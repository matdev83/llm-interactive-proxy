"""
Unit tests for Qwen OAuth connector.

These tests mock external dependencies and don't require network access.
"""

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import httpx
import pytest
from fastapi import HTTPException
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.common.exceptions import BackendError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import (
    ResponseEnvelope,
    StreamingResponseEnvelope,
)

# from starlette.responses import StreamingResponse  # Not needed anymore


class TestQwenOAuthConnectorUnit:
    """Unit tests for QwenOAuthConnector without network dependencies."""

    @pytest.fixture
    def mock_client(self):
        """Mock httpx.AsyncClient."""
        return MagicMock(spec=httpx.AsyncClient)

    @pytest.fixture
    def connector(self, mock_client):
        """QwenOAuthConnector instance with mocked client."""
        return QwenOAuthConnector(mock_client)

    @pytest.fixture
    def mock_credentials(self):
        """Mock OAuth credentials."""
        return {
            "access_token": "test-access-token",
            "refresh_token": "test-refresh-token",
            "token_type": "Bearer",
            "resource_url": "portal.qwen.ai",
            "expiry_date": int(time.time() * 1000) + 3600000,  # 1 hour from now
        }

    def test_connector_initialization(self, connector, mock_client):
        """Test connector initialization."""
        assert connector.name == "qwen-oauth"
        assert connector.client == mock_client
        assert not connector.is_functional
        assert len(connector.available_models) == 0
        # Verify it inherits from OpenAIConnector
        assert (
            connector._default_endpoint
            == "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        assert connector.api_base_url == connector._default_endpoint

    @pytest.mark.asyncio
    async def test_initialize_with_valid_credentials(self, connector, mock_credentials):
        """Test initialization with valid OAuth credentials."""
        with (
            patch("pathlib.Path.home") as mock_home,
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data=json.dumps(mock_credentials))),
        ):

            mock_home.return_value = Path("/mock/home")

            await connector.initialize()

            assert connector.is_functional
            assert len(connector.available_models) > 0
            assert "qwen3-coder-plus" in connector.available_models
            assert "qwen3-coder-flash" in connector.available_models
            # Verify the API base URL is updated from credentials
            assert connector.api_base_url == "https://portal.qwen.ai/v1"

    @pytest.mark.asyncio
    async def test_initialize_without_credentials(self, connector):
        """Test initialization when credentials file doesn't exist."""
        with patch("pathlib.Path.exists", return_value=False):
            await connector.initialize()

            assert not connector.is_functional
            assert len(connector.available_models) == 0

    @pytest.mark.asyncio
    async def test_initialize_with_invalid_credentials(self, connector):
        """Test initialization with invalid credentials file."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="invalid json")),
        ):

            await connector.initialize()

            assert not connector.is_functional

    def test_get_access_token(self, connector, mock_credentials):
        """Test getting access token from credentials."""
        connector._oauth_credentials = mock_credentials

        token = connector._get_access_token()

        assert token == "test-access-token"

    def test_get_access_token_no_credentials(self, connector):
        """Test getting access token when no credentials are loaded."""
        token = connector._get_access_token()

        assert token is None

    def test_get_endpoint_url_with_resource_url(self, connector, mock_credentials):
        """Test getting endpoint URL when resource_url is provided."""
        connector._oauth_credentials = mock_credentials

        url = connector._get_endpoint_url()

        assert url == "https://portal.qwen.ai/v1"

    def test_get_endpoint_url_without_protocol(self, connector):
        """Test getting endpoint URL when resource_url lacks protocol."""
        connector._oauth_credentials = {"resource_url": "portal.qwen.ai"}

        url = connector._get_endpoint_url()

        assert url == "https://portal.qwen.ai/v1"

    def test_get_endpoint_url_default(self, connector):
        """Test getting endpoint URL when no resource_url is provided."""
        connector._oauth_credentials = {}

        url = connector._get_endpoint_url()

        assert url == "https://dashscope.aliyuncs.com/compatible-mode/v1"

    def test_is_token_expired_valid_token(self, connector, mock_credentials):
        """Test token expiry check with valid token."""
        connector._oauth_credentials = mock_credentials

        with patch("time.time", return_value=time.time()):
            is_expired = connector._is_token_expired()

            assert not is_expired

    def test_is_token_expired_expired_token(self, connector):
        """Test token expiry check with expired token."""
        expired_credentials = {
            "expiry_date": int(time.time() * 1000) - 3600000  # 1 hour ago
        }
        connector._oauth_credentials = expired_credentials

        is_expired = connector._is_token_expired()

        assert is_expired

    def test_is_token_expired_no_expiry(self, connector):
        """Test token expiry check when no expiry date is set."""
        connector._oauth_credentials = {"access_token": "test"}

        is_expired = connector._is_token_expired()

        assert not is_expired  # Assume valid if no expiry

    def test_get_headers(self, connector, mock_credentials):
        """Test that get_headers returns OAuth headers."""
        connector._oauth_credentials = mock_credentials

        headers = connector.get_headers()

        assert headers["Authorization"] == "Bearer test-access-token"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"

    def test_get_headers_no_token(self, connector):
        """Test that get_headers raises exception when no token is available."""
        connector._oauth_credentials = None

        with pytest.raises(HTTPException) as exc_info:
            connector.get_headers()

        assert exc_info.value.status_code == 401
        assert "No valid Qwen OAuth access token available" in str(
            exc_info.value.detail
        )

    @pytest.mark.asyncio
    async def test_refresh_token_success(self, connector, mock_client):
        """Test successful token refresh."""
        connector._oauth_credentials = {
            "refresh_token": "test-refresh-token",
            "expiry_date": int(time.time() * 1000) - 3600000,  # Expired token
        }

        # Mock successful refresh response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "resource_url": "portal.qwen.ai",
        }
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(connector, "_save_oauth_credentials", AsyncMock()):
            success = await connector._refresh_token_if_needed()

            assert success
            assert connector._oauth_credentials["access_token"] == "new-access-token"
            # Verify the API base URL is updated
            assert connector.api_base_url == "https://portal.qwen.ai/v1"

    @pytest.mark.asyncio
    async def test_refresh_token_no_refresh_token(self, connector):
        """Test token refresh when no refresh token is available."""
        connector._oauth_credentials = {"access_token": "test"}

        with patch.object(connector, "_is_token_expired", return_value=True):
            success = await connector._refresh_token_if_needed()

            assert not success

    @pytest.mark.asyncio
    async def test_refresh_token_http_error(self, connector, mock_client):
        """Test token refresh with HTTP error."""
        connector._oauth_credentials = {"refresh_token": "test-refresh-token"}

        # Mock failed refresh response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Invalid refresh token"
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch.object(connector, "_is_token_expired", return_value=True):
            success = await connector._refresh_token_if_needed()

            assert not success

    def test_get_available_models_functional(self, connector):
        """Test getting available models when connector is functional."""
        connector.is_functional = True
        connector.available_models = ["qwen3-coder-plus", "qwen3-coder-flash"]

        models = connector.get_available_models()

        assert models == ["qwen3-coder-plus", "qwen3-coder-flash"]

    def test_get_available_models_not_functional(self, connector):
        """Test getting available models when connector is not functional."""
        connector.is_functional = False
        connector.available_models = ["qwen3-coder-plus", "qwen3-coder-flash"]

        models = connector.get_available_models()

        assert models == []

    @pytest.mark.asyncio
    async def test_chat_completions_success(self, connector, mock_client):
        """Test successful chat completion."""
        # Setup
        connector._oauth_credentials = {
            "access_token": "test-token",
            "resource_url": "portal.qwen.ai",
        }
        connector.api_base_url = "https://portal.qwen.ai/v1"

        test_message = ChatMessage(role="user", content="Hello")
        request_data = ChatRequest(
            model="qwen3-coder-plus", messages=[test_message], stream=False
        )

        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "test-id",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        mock_response.headers = {"content-type": "application/json"}
        mock_client.post = AsyncMock(return_value=mock_response)

        # Mock parent class methods
        with (
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=True)
            ),
            patch.object(
                connector,
                "_prepare_payload",
                return_value={
                    "model": "qwen3-coder-plus",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            ),
            patch.object(
                connector,
                "_handle_non_streaming_response",
                AsyncMock(
                    return_value=ResponseEnvelope(
                        content=mock_response.json.return_value,
                        headers=mock_response.headers,
                        status_code=mock_response.status_code,
                    )
                ),
            ),
        ):

            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

            assert isinstance(result, ResponseEnvelope)
            assert "choices" in result.content
            assert result.content["choices"][0]["message"]["content"] == "Hello!"

    @pytest.mark.asyncio
    async def test_chat_completions_with_prefix(self, connector, mock_client):
        """Test chat completion with qwen-oauth: prefix in model name."""
        # Setup
        connector._oauth_credentials = {
            "access_token": "test-token",
            "resource_url": "portal.qwen.ai",
        }
        connector.api_base_url = "https://portal.qwen.ai/v1"

        test_message = ChatMessage(role="user", content="Hello")
        request_data = ChatRequest(
            model="qwen-oauth:qwen3-coder-plus", messages=[test_message], stream=False
        )

        # Mock successful API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "test-id",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        mock_response.headers = {"content-type": "application/json"}

        # Create a mock for the parent class method
        from src.core.domain.responses import ResponseEnvelope

        parent_mock = AsyncMock(
            return_value=ResponseEnvelope(
                content=mock_response.json.return_value,
                headers=mock_response.headers,
                status_code=mock_response.status_code,
            )
        )

        # Mock parent class methods
        with (
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=True)
            ),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions", parent_mock
            ),
        ):

            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen-oauth:qwen3-coder-plus",
            )

            # Verify the prefix was stripped
            # Check that the parent method was called with the correct model name
            assert parent_mock.call_args is not None
            _, kwargs = parent_mock.call_args
            assert kwargs["effective_model"] == "qwen3-coder-plus"

            assert isinstance(result, ResponseEnvelope)
            assert "choices" in result.content
            assert result.content["choices"][0]["message"]["content"] == "Hello!"

    @pytest.mark.asyncio
    async def test_chat_completions_streaming(self, connector, mock_client):
        """Test streaming chat completion."""
        # Setup
        connector._oauth_credentials = {
            "access_token": "test-token",
            "resource_url": "portal.qwen.ai",
        }
        connector.api_base_url = "https://portal.qwen.ai/v1"

        test_message = ChatMessage(role="user", content="Hello")
        request_data = ChatRequest(
            model="qwen3-coder-plus", messages=[test_message], stream=True
        )

        # Mock streaming response
        mock_stream_response = StreamingResponseEnvelope(
            content=AsyncMock(), media_type="text/event-stream"
        )

        # Mock parent class methods
        with (
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=True)
            ),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                AsyncMock(return_value=mock_stream_response),
            ),
        ):

            result = await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

            assert isinstance(result, StreamingResponseEnvelope)
            assert result.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_chat_completions_token_refresh_failure(self, connector):
        """Test chat completion when token refresh fails."""
        test_message = ChatMessage(role="user", content="Hello")
        request_data = ChatRequest(
            model="qwen3-coder-plus", messages=[test_message], stream=False
        )

        with patch.object(
            connector, "_refresh_token_if_needed", AsyncMock(return_value=False)
        ):
            with pytest.raises(HTTPException) as exc_info:
                await connector.chat_completions(
                    request_data=request_data,
                    processed_messages=[test_message],
                    effective_model="qwen3-coder-plus",
                )

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_chat_completions_exception_handling(self, connector, mock_client):
        """Test chat completion exception handling."""
        # Setup
        connector._oauth_credentials = {
            "access_token": "test-token",
            "resource_url": "portal.qwen.ai",
        }

        test_message = ChatMessage(role="user", content="Hello")
        request_data = ChatRequest(
            model="qwen3-coder-plus", messages=[test_message], stream=False
        )

        # Mock parent class methods to raise exception
        with (
            patch.object(
                connector, "_refresh_token_if_needed", AsyncMock(return_value=True)
            ),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                AsyncMock(side_effect=Exception("Test error")),
            ),
            pytest.raises(BackendError) as exc_info,
        ):
            # The exception should be caught and wrapped in a BackendError
            await connector.chat_completions(
                request_data=request_data,
                processed_messages=[test_message],
                effective_model="qwen3-coder-plus",
            )

        # Verify the BackendError contains the original error message
        assert "Test error" in str(exc_info.value)
        assert "Qwen OAuth chat completion failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_save_oauth_credentials(self, connector, mock_credentials):
        """Test saving OAuth credentials to file."""
        connector._oauth_credentials = mock_credentials

        with (
            patch("pathlib.Path.home") as mock_home,
            patch("pathlib.Path.mkdir") as mock_mkdir,
            patch("builtins.open", mock_open()) as mock_file,
        ):

            mock_home.return_value = Path("/mock/home")

            await connector._save_oauth_credentials()

            # Verify directory creation was attempted
            mock_mkdir.assert_called_once()

            # Verify file was opened for writing
            mock_file.assert_called_once()

            # Verify JSON was written
            handle = mock_file()
            written_data = "".join(call.args[0] for call in handle.write.call_args_list)
            parsed_data = json.loads(written_data)

            assert parsed_data["access_token"] == "test-access-token"
            assert parsed_data["refresh_token"] == "test-refresh-token"


class TestQwenOAuthConnectorEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.fixture
    def mock_client(self):
        """Mock httpx.AsyncClient."""
        return MagicMock(spec=httpx.AsyncClient)

    @pytest.fixture
    def connector(self, mock_client):
        """QwenOAuthConnector instance with mocked client."""
        return QwenOAuthConnector(mock_client)

    @pytest.mark.asyncio
    async def test_malformed_credentials_file(self, connector):
        """Test handling of malformed credentials file."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", mock_open(read_data="{ invalid json")),
        ):

            await connector.initialize()

            assert not connector.is_functional

    @pytest.mark.asyncio
    async def test_credentials_file_permission_error(self, connector):
        """Test handling of permission errors when reading credentials."""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("builtins.open", side_effect=PermissionError("Access denied")),
        ):

            await connector.initialize()

            assert not connector.is_functional

    @pytest.mark.asyncio
    async def test_network_error_during_refresh(self, connector, mock_client):
        """Test handling of network errors during token refresh."""
        connector._oauth_credentials = {"refresh_token": "test-refresh-token"}

        # Mock network error
        mock_client.post = AsyncMock(side_effect=httpx.RequestError("Network error"))

        with patch.object(connector, "_is_token_expired", return_value=True):
            success = await connector._refresh_token_if_needed()

            assert not success


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v"])
