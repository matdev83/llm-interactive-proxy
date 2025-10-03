"""Enhanced tests for Qwen OAuth connector error handling and initialization."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from fastapi import HTTPException
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.common.exceptions import BackendError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope


class TestQwenOAuthEnhancedErrorHandling:
    """Test cases focusing on Qwen OAuth error handling and initialization."""

    @pytest.fixture
    def connector(self):
        """Create a QwenOAuth connector with a mocked httpx client."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        from src.core.config.app_config import AppConfig

        config = AppConfig()
        connector = QwenOAuthConnector(mock_client, config=config)
        return connector

    @pytest.mark.asyncio
    async def test_initialize_success(self, connector):
        """Test successful initialization with credentials loading."""
        with (
            patch.object(
                connector, "_load_oauth_credentials", return_value=True
            ) as mock_load,
            patch.object(
                connector, "_refresh_token_if_needed", return_value=True
            ) as mock_refresh,
        ):
            await connector.initialize()
            mock_load.assert_awaited_once()
            mock_refresh.assert_awaited_once()
            assert connector.is_functional is True
            assert len(connector.available_models) > 0
            assert "qwen3-coder-plus" in connector.available_models

    @pytest.mark.asyncio
    async def test_initialize_failure(self, connector):
        """Test initialization failure when credentials cannot be loaded."""
        with patch.object(
            connector, "_load_oauth_credentials", return_value=False
        ) as mock_load:
            await connector.initialize()
            mock_load.assert_awaited_once()
            assert connector.is_functional is False
            # Even though available_models is set, get_available_models should return empty list
            assert connector.get_available_models() == []

    @pytest.mark.asyncio
    async def test_get_endpoint_url_no_credentials(self, connector):
        """Test getting endpoint URL when no credentials are loaded."""
        connector._oauth_credentials = None
        assert connector._get_endpoint_url() == connector._default_endpoint

    @pytest.mark.asyncio
    async def test_is_token_expired_no_credentials(self, connector):
        """Test token expiry check when no credentials are loaded."""
        connector._oauth_credentials = None
        assert connector._is_token_expired() is True

    @pytest.mark.asyncio
    async def test_is_token_expired_no_expiry_date(self, connector):
        """Test token expiry check when credentials have no expiry date."""
        connector._oauth_credentials = {"access_token": "test_token"}
        assert connector._is_token_expired() is False

    @pytest.mark.asyncio
    async def test_token_refresh_check_not_expired(self, connector):
        """Test refresh token check when token is not expired."""
        with patch.object(connector, "_is_token_expired", return_value=False):
            assert await connector._refresh_token_if_needed() is True

    @pytest.mark.asyncio
    async def test_chat_completions_generic_error_handling(self, connector):
        """Test generic error handling in chat_completions method."""
        # Setup test data
        request = ChatRequest(
            model="qwen3-coder-plus",
            messages=[ChatMessage(role="user", content="Hello")],
        )
        processed_messages = [ChatMessage(role="user", content="Hello")]

        # Mock validation to pass, token refresh to succeed and parent class method to raise an exception
        with (
            patch.object(
                connector, "_validate_runtime_credentials", AsyncMock(return_value=True)
            ),
            patch.object(connector, "_refresh_token_if_needed", return_value=True),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                side_effect=Exception("Test error"),
            ),
            pytest.raises(BackendError) as exc_info,
        ):
            # Execute and verify the exception is wrapped in BackendError
            await connector.chat_completions(
                request_data=request,
                processed_messages=processed_messages,
                effective_model="qwen3-coder-plus",
            )

        # Verify the BackendError contains the original error message
        assert "Test error" in str(exc_info.value)
        assert "Qwen OAuth chat completion failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_model_prefix_stripping(self, connector):
        """Test that the qwen-oauth: prefix is properly stripped from model names."""
        # Setup
        request = ChatRequest(
            model="qwen-oauth:qwen3-coder-plus",
            messages=[ChatMessage(role="user", content="Hello")],
        )
        processed_messages = [{"role": "user", "content": "Hello"}]

        # Mock validation to pass, token refresh to succeed and parent class method
        with (
            patch.object(
                connector, "_validate_runtime_credentials", AsyncMock(return_value=True)
            ),
            patch.object(connector, "_refresh_token_if_needed", return_value=True),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                AsyncMock(
                    return_value=ResponseEnvelope(content={"id": "test"}, headers={})
                ),
            ) as mock_parent,
        ):

            # Execute
            await connector.chat_completions(
                request_data=request,
                processed_messages=processed_messages,
                effective_model="qwen-oauth:qwen3-coder-plus",
            )

            # Verify that the model name was properly modified
            call_args = mock_parent.call_args
            assert call_args[1]["effective_model"] == "qwen3-coder-plus"
            sent_request = call_args[1]["request_data"]
            assert sent_request.model == "qwen3-coder-plus"

    @pytest.mark.asyncio
    async def test_http_exception_passthrough(self, connector):
        """Test that HTTPExceptions from parent class are passed through."""
        request = ChatRequest(
            model="qwen3-coder-plus",
            messages=[ChatMessage(role="user", content="Hello")],
        )
        processed_messages = [{"role": "user", "content": "Hello"}]

        # Mock validation to pass, token refresh to succeed and parent class to raise HTTPException
        http_exception = HTTPException(status_code=429, detail="Rate limited")
        with (
            patch.object(
                connector, "_validate_runtime_credentials", AsyncMock(return_value=True)
            ),
            patch.object(connector, "_refresh_token_if_needed", return_value=True),
            patch(
                "src.connectors.openai.OpenAIConnector.chat_completions",
                side_effect=http_exception,
            ),
        ):

            # Execute and verify exception is re-raised
            with pytest.raises(HTTPException) as exc_info:
                await connector.chat_completions(
                    request_data=request,
                    processed_messages=processed_messages,
                    effective_model="qwen3-coder-plus",
                )

            assert exc_info.value.status_code == 429
            assert exc_info.value.detail == "Rate limited"

    @pytest.mark.asyncio
    async def test_chat_completions_refresh_token_failure(self, connector):
        """Test chat_completions when token refresh fails."""
        # Setup
        request = ChatRequest(
            model="qwen3-coder-plus",
            messages=[ChatMessage(role="user", content="Hello")],
        )
        processed_messages = [{"role": "user", "content": "Hello"}]

        # Mock validation to pass and token refresh to fail
        with (
            patch.object(
                connector, "_validate_runtime_credentials", AsyncMock(return_value=True)
            ),
            patch.object(connector, "_refresh_token_if_needed", return_value=False),
        ):
            # Verify that HTTPException is raised with 401 status code
            with pytest.raises(HTTPException) as exc_info:
                await connector.chat_completions(
                    request_data=request,
                    processed_messages=processed_messages,
                    effective_model="qwen3-coder-plus",
                )

            assert exc_info.value.status_code == 401
            assert "Failed to refresh Qwen OAuth token" in exc_info.value.detail
