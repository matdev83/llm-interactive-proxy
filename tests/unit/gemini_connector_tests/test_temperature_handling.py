from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.connectors.gemini import GeminiBackend
from src.models import ChatCompletionRequest, ChatMessage


class TestGeminiTemperatureHandling:
    """Test temperature handling in Gemini connector."""

    @pytest.fixture
    def gemini_backend(self):
        """Create a GeminiBackend instance for testing."""
        mock_client = AsyncMock()
        return GeminiBackend(mock_client)

    @pytest.fixture
    def sample_request_data(self):
        """Create sample request data for testing."""
        return ChatCompletionRequest(
            model="gemini-2.5-pro",
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
    async def test_temperature_added_to_generation_config(self, gemini_backend, sample_request_data, sample_processed_messages):
        """Test that temperature is properly added to generationConfig."""
        # Set temperature in request data
        sample_request_data.temperature = 0.7

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Test response"}]
                    },
                    "finishReason": "STOP"
                }
            ]
        }
        mock_response.headers = {}

        gemini_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        await gemini_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
            api_key="test-key"
        )

        # Verify the call was made with temperature in generationConfig
        gemini_backend.client.post.assert_called_once()
        call_args = gemini_backend.client.post.call_args
        payload = call_args[1]["json"]  # keyword argument
        
        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]
        assert payload["generationConfig"]["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_temperature_clamping_above_one(self, gemini_backend, sample_request_data, sample_processed_messages):
        """Test that temperature > 1.0 is clamped to 1.0 for Gemini."""
        # Set temperature above 1.0
        sample_request_data.temperature = 1.5

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Test response"}]
                    },
                    "finishReason": "STOP"
                }
            ]
        }
        mock_response.headers = {}

        gemini_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        with patch('src.connectors.gemini.logger') as mock_logger:
            await gemini_backend.chat_completions(
                request_data=sample_request_data,
                processed_messages=sample_processed_messages,
                effective_model="gemini-2.5-pro",
                gemini_api_base_url="https://generativelanguage.googleapis.com",
                api_key="test-key"
            )

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            warning_call = mock_logger.warning.call_args[0][0]
            assert "Temperature 1.5 > 1.0 for Gemini, clamping to 1.0" in warning_call

        # Verify the call was made with clamped temperature
        gemini_backend.client.post.assert_called_once()
        call_args = gemini_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]
        assert payload["generationConfig"]["temperature"] == 1.0  # Clamped value

    @pytest.mark.asyncio
    async def test_temperature_zero_value(self, gemini_backend, sample_request_data, sample_processed_messages):
        """Test that temperature 0.0 is properly handled."""
        # Set temperature to 0.0
        sample_request_data.temperature = 0.0

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Test response"}]
                    },
                    "finishReason": "STOP"
                }
            ]
        }
        mock_response.headers = {}

        gemini_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        await gemini_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
            api_key="test-key"
        )

        # Verify the call was made with temperature 0.0
        gemini_backend.client.post.assert_called_once()
        call_args = gemini_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]
        assert payload["generationConfig"]["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_temperature_with_existing_generation_config(self, gemini_backend, sample_request_data, sample_processed_messages):
        """Test that temperature is added to existing generationConfig."""
        # Set temperature and existing generation config
        sample_request_data.temperature = 0.8
        sample_request_data.generation_config = {
            "maxOutputTokens": 1000,
            "topP": 0.9
        }

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Test response"}]
                    },
                    "finishReason": "STOP"
                }
            ]
        }
        mock_response.headers = {}

        gemini_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        await gemini_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
            api_key="test-key"
        )

        # Verify the call was made with both temperature and existing config
        gemini_backend.client.post.assert_called_once()
        call_args = gemini_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]
        assert payload["generationConfig"]["temperature"] == 0.8
        assert "maxOutputTokens" in payload["generationConfig"]
        assert payload["generationConfig"]["maxOutputTokens"] == 1000
        assert "topP" in payload["generationConfig"]
        assert payload["generationConfig"]["topP"] == 0.9

    @pytest.mark.asyncio
    async def test_temperature_with_thinking_budget(self, gemini_backend, sample_request_data, sample_processed_messages):
        """Test that temperature works alongside thinking budget."""
        # Set both temperature and thinking budget
        sample_request_data.temperature = 0.6
        sample_request_data.thinking_budget = 2048

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Test response"}]
                    },
                    "finishReason": "STOP"
                }
            ]
        }
        mock_response.headers = {}

        gemini_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        await gemini_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
            api_key="test-key"
        )

        # Verify both temperature and thinking budget are in generationConfig
        gemini_backend.client.post.assert_called_once()
        call_args = gemini_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]
        assert payload["generationConfig"]["temperature"] == 0.6
        assert "thinkingConfig" in payload["generationConfig"]
        assert "thinkingBudget" in payload["generationConfig"]["thinkingConfig"]
        assert payload["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 2048

    @pytest.mark.asyncio
    async def test_no_temperature_no_generation_config(self, gemini_backend, sample_request_data, sample_processed_messages):
        """Test that no generationConfig is created when temperature is not set."""
        # Don't set temperature (should be None)
        assert sample_request_data.temperature is None

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Test response"}]
                    },
                    "finishReason": "STOP"
                }
            ]
        }
        mock_response.headers = {}

        gemini_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        await gemini_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
            api_key="test-key"
        )

        # Verify no generationConfig was created for temperature
        gemini_backend.client.post.assert_called_once()
        call_args = gemini_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        # generationConfig should not exist or should not contain temperature
        if "generationConfig" in payload:
            assert "temperature" not in payload["generationConfig"]

    @pytest.mark.asyncio
    async def test_temperature_with_extra_params_override(self, gemini_backend, sample_request_data, sample_processed_messages):
        """Test that extra_params can override temperature setting."""
        # Set temperature in request data
        sample_request_data.temperature = 0.7
        
        # Set extra_params with generationConfig that includes temperature
        sample_request_data.extra_params = {
            "generationConfig": {
                "temperature": 0.3  # Should override the direct temperature setting
            }
        }

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Test response"}]
                    },
                    "finishReason": "STOP"
                }
            ]
        }
        mock_response.headers = {}

        gemini_backend.client.post = AsyncMock(return_value=mock_response)

        # Call the method
        await gemini_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
            api_key="test-key"
        )

        # Verify extra_params temperature overrode the direct temperature
        gemini_backend.client.post.assert_called_once()
        call_args = gemini_backend.client.post.call_args
        payload = call_args[1]["json"]
        
        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]
        # extra_params should override, so temperature should be 0.3, not 0.7
        assert payload["generationConfig"]["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_temperature_streaming_request(self, gemini_backend, sample_request_data, sample_processed_messages):
        """Test temperature handling in streaming requests."""
        # Set temperature and enable streaming
        sample_request_data.temperature = 0.9
        sample_request_data.stream = True

        # Mock streaming response
        mock_response = Mock()
        mock_response.status_code = 200  # This should be an int, not AsyncMock
        mock_response.aiter_text.return_value = [
            '{"candidates": [{"content": {"parts": [{"text": "Streaming response"}]}}]}'
        ]
        mock_response.aclose = AsyncMock()

        # Mock the client.send method instead of client.stream
        gemini_backend.client.build_request = Mock()
        gemini_backend.client.send = AsyncMock(return_value=mock_response)

        # Call the method
        await gemini_backend.chat_completions(
            request_data=sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
            api_key="test-key"
        )

        # Verify the request was built with temperature in payload
        gemini_backend.client.build_request.assert_called_once()
        call_args = gemini_backend.client.build_request.call_args
        payload = call_args[1]["json"]
        
        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]
        assert payload["generationConfig"]["temperature"] == 0.9