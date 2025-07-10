import pytest
from unittest.mock import AsyncMock, Mock, patch

from src.connectors.openrouter import OpenRouterBackend
from src.models import ChatCompletionRequest, ChatMessage


class TestOpenRouterTemperatureHandling:
    """Test temperature handling in OpenRouter connector."""

    @pytest.fixture
    def openrouter_backend(self):
        """Create an OpenRouterBackend instance for testing."""
        mock_client = AsyncMock()
        return OpenRouterBackend(mock_client)

    @pytest.fixture
    def sample_request_data(self):
        """Create sample request data for testing."""
        return ChatCompletionRequest(
            model="openrouter:openai/gpt-4",
            messages=[
                ChatMessage(role="user", content="Test message")
            ]
        )

    @pytest.fixture
    def sample_processed_messages(self):
        """Create sample processed messages for testing."""
        return [
            ChatMessage(role="user", content="Test message")
        ]

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_temperature_added_to_payload(self, openrouter_backend, sample_request_data, sample_processed_messages):
        """Test that temperature is properly added to the request payload."""
        # Set temperature in request data
        sample_request_data.temperature = 0.7

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Test response"},
                    "finish_reason": "stop"
                }
            ]
        }
        mock_response.headers = {}

        openrouter_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        result = await openrouter_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="openai/gpt-4",
            api_key="test-key"
        )

        # Verify the call was made with temperature in payload
        openrouter_backend.client.post.assert_called_once()
        call_args = openrouter_backend.client.post.call_args
        payload = call_args[1]["json"]  # keyword argument
        
        assert "temperature" in payload
        assert payload["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_temperature_zero_value(self, openrouter_backend, sample_request_data, sample_processed_messages):
        """Test that temperature 0.0 is properly handled."""
        # Set temperature to 0.0
        sample_request_data.temperature = 0.0

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Test response"},
                    "finish_reason": "stop"
                }
            ]
        }
        mock_response.headers = {}

        openrouter_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        result = await openrouter_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="openai/gpt-4",
            api_key="test-key"
        )

        # Verify the call was made with temperature 0.0
        openrouter_backend.client.post.assert_called_once()
        call_args = openrouter_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "temperature" in payload
        assert payload["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_temperature_max_value(self, openrouter_backend, sample_request_data, sample_processed_messages):
        """Test that temperature 2.0 (max OpenAI value) is properly handled."""
        # Set temperature to 2.0
        sample_request_data.temperature = 2.0

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Test response"},
                    "finish_reason": "stop"
                }
            ]
        }
        mock_response.headers = {}

        openrouter_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        result = await openrouter_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="openai/gpt-4",
            api_key="test-key"
        )

        # Verify the call was made with temperature 2.0
        openrouter_backend.client.post.assert_called_once()
        call_args = openrouter_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "temperature" in payload
        assert payload["temperature"] == 2.0

    @pytest.mark.asyncio
    async def test_temperature_with_extra_params(self, openrouter_backend, sample_request_data, sample_processed_messages):
        """Test that temperature works alongside extra_params."""
        # Set temperature and extra params
        sample_request_data.temperature = 0.8
        sample_request_data.extra_params = {
            "top_p": 0.9,
            "max_tokens": 1000,
            "frequency_penalty": 0.1
        }

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Test response"},
                    "finish_reason": "stop"
                }
            ]
        }
        mock_response.headers = {}

        openrouter_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        result = await openrouter_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="openai/gpt-4",
            api_key="test-key"
        )

        # Verify both temperature and extra params are in payload
        openrouter_backend.client.post.assert_called_once()
        call_args = openrouter_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "temperature" in payload
        assert payload["temperature"] == 0.8
        assert "top_p" in payload
        assert payload["top_p"] == 0.9
        assert "max_tokens" in payload
        assert payload["max_tokens"] == 1000
        assert "frequency_penalty" in payload
        assert payload["frequency_penalty"] == 0.1

    @pytest.mark.asyncio
    async def test_temperature_with_reasoning_effort(self, openrouter_backend, sample_request_data, sample_processed_messages):
        """Test that temperature works alongside reasoning effort."""
        # Set both temperature and reasoning effort
        sample_request_data.temperature = 0.6
        sample_request_data.reasoning_effort = "medium"

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Test response"},
                    "finish_reason": "stop"
                }
            ]
        }
        mock_response.headers = {}

        openrouter_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        result = await openrouter_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="openai/gpt-4",
            api_key="test-key"
        )

        # Verify both temperature and reasoning effort are in payload
        openrouter_backend.client.post.assert_called_once()
        call_args = openrouter_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "temperature" in payload
        assert payload["temperature"] == 0.6
        assert "reasoning_effort" in payload
        assert payload["reasoning_effort"] == "medium"

    @pytest.mark.asyncio
    async def test_temperature_with_reasoning_config(self, openrouter_backend, sample_request_data, sample_processed_messages):
        """Test that temperature works alongside reasoning config."""
        # Set both temperature and reasoning config
        sample_request_data.temperature = 0.5
        sample_request_data.reasoning = {
            "effort": "high",
            "max_tokens": 2048
        }

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Test response"},
                    "finish_reason": "stop"
                }
            ]
        }
        mock_response.headers = {}

        openrouter_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        result = await openrouter_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="openai/gpt-4",
            api_key="test-key"
        )

        # Verify both temperature and reasoning config are in payload
        openrouter_backend.client.post.assert_called_once()
        call_args = openrouter_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "temperature" in payload
        assert payload["temperature"] == 0.5
        assert "reasoning" in payload
        assert payload["reasoning"]["effort"] == "high"
        assert payload["reasoning"]["max_tokens"] == 2048

    @pytest.mark.asyncio
    async def test_no_temperature_not_in_payload(self, openrouter_backend, sample_request_data, sample_processed_messages):
        """Test that temperature is not included when not set."""
        # Don't set temperature (should be None)
        assert sample_request_data.temperature is None

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Test response"},
                    "finish_reason": "stop"
                }
            ]
        }
        mock_response.headers = {}

        openrouter_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        result = await openrouter_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="openai/gpt-4",
            api_key="test-key"
        )

        # Verify temperature is not in payload
        openrouter_backend.client.post.assert_called_once()
        call_args = openrouter_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "temperature" not in payload

    @pytest.mark.asyncio
    async def test_temperature_with_extra_params_override(self, openrouter_backend, sample_request_data, sample_processed_messages):
        """Test that extra_params can override temperature setting."""
        # Set temperature in request data
        sample_request_data.temperature = 0.7
        
        # Set extra_params with temperature that should override
        sample_request_data.extra_params = {
            "temperature": 0.3  # Should override the direct temperature setting
        }

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Test response"},
                    "finish_reason": "stop"
                }
            ]
        }
        mock_response.headers = {}

        openrouter_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        result = await openrouter_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="openai/gpt-4",
            api_key="test-key"
        )

        # Verify extra_params temperature overrode the direct temperature
        openrouter_backend.client.post.assert_called_once()
        call_args = openrouter_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "temperature" in payload
        # extra_params should override, so temperature should be 0.3, not 0.7
        assert payload["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_temperature_streaming_request(self, openrouter_backend, sample_request_data, sample_processed_messages):
        """Test temperature handling in streaming requests."""
        # Set temperature and enable streaming
        sample_request_data.temperature = 0.9
        sample_request_data.stream = True

        # Mock streaming response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.aiter_text.return_value = [
            'data: {"choices": [{"delta": {"content": "Streaming"}}]}\n\n',
            'data: {"choices": [{"delta": {"content": " response"}}]}\n\n',
            'data: [DONE]\n\n'
        ]
        mock_response.aclose = AsyncMock()

        openrouter_backend.client.stream = AsyncMock()
        openrouter_backend.client.stream.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        openrouter_backend.client.stream.return_value.__aexit__ = AsyncMock(return_value=None)

        # Call the method
        result = await openrouter_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="openai/gpt-4",
            api_key="test-key"
        )

        # Verify streaming was called with temperature in payload
        openrouter_backend.client.stream.assert_called_once()
        call_args = openrouter_backend.client.stream.call_args
        payload = call_args[1]["json"]
        
        assert "temperature" in payload
        assert payload["temperature"] == 0.9
        assert "stream" in payload
        assert payload["stream"] is True

    @pytest.mark.asyncio
    async def test_temperature_with_all_standard_params(self, openrouter_backend, sample_request_data, sample_processed_messages):
        """Test temperature alongside all standard OpenAI parameters."""
        # Set temperature and other standard parameters
        sample_request_data.temperature = 0.8
        sample_request_data.max_tokens = 1500
        sample_request_data.top_p = 0.95
        sample_request_data.frequency_penalty = 0.2
        sample_request_data.presence_penalty = 0.1
        sample_request_data.stop = ["END", "STOP"]

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {"content": "Test response"},
                    "finish_reason": "stop"
                }
            ]
        }
        mock_response.headers = {}

        openrouter_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        result = await openrouter_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="openai/gpt-4",
            api_key="test-key"
        )

        # Verify all parameters including temperature are in payload
        openrouter_backend.client.post.assert_called_once()
        call_args = openrouter_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "temperature" in payload
        assert payload["temperature"] == 0.8
        assert "max_tokens" in payload
        assert payload["max_tokens"] == 1500
        assert "top_p" in payload
        assert payload["top_p"] == 0.95
        assert "frequency_penalty" in payload
        assert payload["frequency_penalty"] == 0.2
        assert "presence_penalty" in payload
        assert payload["presence_penalty"] == 0.1
        assert "stop" in payload
        assert payload["stop"] == ["END", "STOP"] 