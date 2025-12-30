"""
Tests for Qwen OAuth token usage calculation functionality.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.connectors.qwen_oauth import QwenOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope


class TestQwenOAuthTokenUsage:
    """Test cases for Qwen OAuth token usage calculation."""

    @pytest.fixture
    def mock_config(self):
        """Create a mock config for testing."""
        config = MagicMock(spec=AppConfig)
        return config

    @pytest.fixture
    def mock_client(self):
        """Create a mock HTTP client for testing."""
        client = AsyncMock()
        return client

    @pytest.fixture
    def qwen_connector(self, mock_client, mock_config):
        """Create a QwenOAuthConnector instance for testing."""
        connector = QwenOAuthConnector(mock_client, mock_config)
        # Mock the OAuth credentials to avoid auth errors
        connector._oauth_credentials = {
            "access_token": "test_token",
            "refresh_token": "test_refresh_token",
            "expiry_date": 9999999999000,  # Far future timestamp
        }
        connector.is_functional = True
        return connector

    def test_calculate_token_usage_basic(self, qwen_connector):
        """Test basic token usage calculation for a simple response."""
        # Mock the token count utility
        with (
            patch("src.core.utils.token_count.count_tokens") as mock_count,
            patch("src.core.utils.token_count.extract_prompt_text") as mock_extract,
        ):

            # Setup mocks
            mock_extract.return_value = "user: Hello, how are you?"
            mock_count.side_effect = [8, 12]  # prompt_tokens, completion_tokens

            # Create test response
            response_envelope = ResponseEnvelope(
                content={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "I'm doing well, thank you for asking!",
                            }
                        }
                    ]
                },
                status_code=200,
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )

            processed_messages = [{"role": "user", "content": "Hello, how are you?"}]

            # Call the method
            result = qwen_connector._calculate_token_usage(
                response_envelope, processed_messages, "qwen-turbo"
            )

            # Verify the result
            expected = {"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20}
            assert result == expected

            # Verify the token counting was called correctly
            mock_extract.assert_called_once_with(processed_messages)
            assert mock_count.call_count == 2

    def test_calculate_token_usage_with_tool_calls(self, qwen_connector):
        """Test token usage calculation with tool calls in the response."""
        with (
            patch("src.core.utils.token_count.count_tokens") as mock_count,
            patch("src.core.utils.token_count.extract_prompt_text") as mock_extract,
        ):

            # Setup mocks
            mock_extract.return_value = "user: Call the weather function"
            mock_count.side_effect = [
                6,  # prompt_tokens
                15,  # completion content tokens
                8,  # function name tokens
                25,  # function arguments tokens
            ]

            # Create test response with tool calls
            response_envelope = ResponseEnvelope(
                content={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "I'll check the weather for you.",
                                "tool_calls": [
                                    {
                                        "type": "function",
                                        "function": {
                                            "name": "get_weather",
                                            "arguments": '{"location": "New York", "units": "celsius"}',
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                },
                status_code=200,
                usage=None,
            )

            processed_messages = [
                {"role": "user", "content": "Call the weather function"}
            ]

            # Call the method
            result = qwen_connector._calculate_token_usage(
                response_envelope, processed_messages, "qwen-turbo"
            )

            # Verify the result
            expected = {
                "prompt_tokens": 6,
                "completion_tokens": 48,  # 15 + 8 + 25
                "total_tokens": 54,
            }
            assert result == expected

    def test_calculate_token_usage_empty_response(self, qwen_connector):
        """Test token usage calculation when response has no content."""
        with (
            patch("src.core.utils.token_count.count_tokens") as mock_count,
            patch("src.core.utils.token_count.extract_prompt_text") as mock_extract,
        ):

            # Setup mocks
            mock_extract.return_value = "user: Hello"
            mock_count.return_value = 5

            # Create empty response
            response_envelope = ResponseEnvelope(
                content={"choices": []}, status_code=200, usage=None
            )

            processed_messages = [{"role": "user", "content": "Hello"}]

            # Call the method
            result = qwen_connector._calculate_token_usage(
                response_envelope, processed_messages, "qwen-turbo"
            )

            # Verify the result
            expected = {"prompt_tokens": 5, "completion_tokens": 0, "total_tokens": 5}
            assert result == expected

    def test_calculate_token_usage_error_handling(self, qwen_connector):
        """Test that the method handles errors gracefully."""
        # Mock the token count utility to raise an exception
        with patch(
            "src.core.utils.token_count.count_tokens",
            side_effect=Exception("Test error"),
        ):

            response_envelope = ResponseEnvelope(
                content={"choices": [{"message": {"content": "test"}}]},
                status_code=200,
                usage=None,
            )

            processed_messages = [{"role": "user", "content": "test"}]

            # Call the method
            result = qwen_connector._calculate_token_usage(
                response_envelope, processed_messages, "qwen-turbo"
            )

            # Should return zero usage on error
            expected = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            assert result == expected

    @pytest.mark.asyncio
    async def test_chat_completions_augments_missing_usage(self, qwen_connector):
        """Test that chat_completions augments missing token usage."""
        # Mock the parent method
        with (
            patch(
                "src.connectors.openai.OpenAIConnector._chat_completions_canonical",
                autospec=True,
            ) as mock_parent,
            patch.object(qwen_connector, "_calculate_token_usage") as mock_calculate,
            patch.object(qwen_connector, "_refresh_token_if_needed", return_value=True),
            patch.object(
                qwen_connector, "_validate_runtime_credentials", return_value=True
            ),
        ):

            # Setup mock parent response with zero usage
            mock_parent.return_value = ResponseEnvelope(
                content={
                    "choices": [
                        {"message": {"role": "assistant", "content": "Test response"}}
                    ]
                },
                status_code=200,
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )

            # Setup mock calculation
            mock_calculate.return_value = {
                "prompt_tokens": 10,
                "completion_tokens": 15,
                "total_tokens": 25,
            }

            # Call the method
            request = ChatRequest(
                model="qwen-turbo",
                messages=[ChatMessage(role="user", content="test")],
            )

            result = await qwen_connector.chat_completions(
                request_data=request,
                processed_messages=[{"role": "user", "content": "test"}],
                effective_model="qwen-turbo",
            )

            # Verify usage was calculated and set
            assert result.usage == {
                "prompt_tokens": 10,
                "completion_tokens": 15,
                "total_tokens": 25,
            }
            mock_calculate.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_completions_preserves_existing_usage(self, qwen_connector):
        """Test that chat_completions preserves existing non-zero usage."""
        # Mock the parent method
        with (
            patch(
                "src.connectors.openai.OpenAIConnector._chat_completions_canonical",
                autospec=True,
            ) as mock_parent,
            patch.object(qwen_connector, "_calculate_token_usage") as mock_calculate,
            patch.object(qwen_connector, "_refresh_token_if_needed", return_value=True),
            patch.object(
                qwen_connector, "_validate_runtime_credentials", return_value=True
            ),
        ):

            # Setup mock parent response with existing usage
            existing_usage = {
                "prompt_tokens": 12,
                "completion_tokens": 18,
                "total_tokens": 30,
            }
            mock_parent.return_value = ResponseEnvelope(
                content={
                    "choices": [
                        {"message": {"role": "assistant", "content": "Test response"}}
                    ]
                },
                status_code=200,
                usage=existing_usage,
            )

            # Call the method
            request = ChatRequest(
                model="qwen-turbo",
                messages=[ChatMessage(role="user", content="test")],
            )

            result = await qwen_connector.chat_completions(
                request_data=request,
                processed_messages=[{"role": "user", "content": "test"}],
                effective_model="qwen-turbo",
            )

            # Verify existing usage was preserved
            assert result.usage == existing_usage
            mock_calculate.assert_not_called()

    @pytest.mark.asyncio
    async def test_chat_completions_handles_partial_zero_usage(self, qwen_connector):
        """Test that chat_completions recalculates when some usage values are zero."""
        # Mock the parent method
        with (
            patch(
                "src.connectors.openai.OpenAIConnector._chat_completions_canonical",
                autospec=True,
            ) as mock_parent,
            patch.object(qwen_connector, "_calculate_token_usage") as mock_calculate,
            patch.object(qwen_connector, "_refresh_token_if_needed", return_value=True),
            patch.object(
                qwen_connector, "_validate_runtime_credentials", return_value=True
            ),
        ):

            # Setup mock parent response with partial zero usage
            mock_parent.return_value = ResponseEnvelope(
                content={
                    "choices": [
                        {"message": {"role": "assistant", "content": "Test response"}}
                    ]
                },
                status_code=200,
                usage={
                    "prompt_tokens": 12,
                    "completion_tokens": 0,
                    "total_tokens": 12,
                },  # completion_tokens is zero
            )

            # Setup mock calculation
            mock_calculate.return_value = {
                "prompt_tokens": 12,
                "completion_tokens": 20,
                "total_tokens": 32,
            }

            # Call the method
            request = ChatRequest(
                model="qwen-turbo",
                messages=[ChatMessage(role="user", content="test")],
            )

            result = await qwen_connector.chat_completions(
                request_data=request,
                processed_messages=[{"role": "user", "content": "test"}],
                effective_model="qwen-turbo",
            )

            # Verify usage was recalculated
            assert result.usage == {
                "prompt_tokens": 12,
                "completion_tokens": 20,
                "total_tokens": 32,
            }
            mock_calculate.assert_called_once()

    def test_calculate_token_usage_different_models(self, qwen_connector):
        """Test that different model names are passed correctly to token counter."""
        with (
            patch("src.core.utils.token_count.count_tokens") as mock_count,
            patch("src.core.utils.token_count.extract_prompt_text") as mock_extract,
        ):

            # Setup mocks
            mock_extract.return_value = "test"
            mock_count.side_effect = [3, 5]

            response_envelope = ResponseEnvelope(
                content={
                    "choices": [
                        {"message": {"role": "assistant", "content": "response"}}
                    ]
                },
                status_code=200,
                usage=None,
            )

            processed_messages = [{"role": "user", "content": "test"}]

            # Test with different model
            qwen_connector._calculate_token_usage(
                response_envelope, processed_messages, "qwen3-coder-plus"
            )

            # Verify model name was passed to token counter
            assert mock_count.call_count == 2
            # Check that the model name was passed in both calls
            mock_count.assert_any_call("test", "qwen3-coder-plus")
            mock_count.assert_any_call("response", "qwen3-coder-plus")
