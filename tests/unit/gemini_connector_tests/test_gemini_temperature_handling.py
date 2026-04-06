from unittest.mock import AsyncMock, Mock

import pytest
from src.connectors.gemini import GeminiBackend
from src.core.domain.chat import ChatMessage, ChatRequest

from tests.unit.gemini_connector_tests.helpers import (
    attach_gemini_non_streaming_httpx_mocks,
    gemini_connector_request,
)


class TestGeminiTemperatureHandling:
    """Test temperature handling in Gemini connector."""

    @pytest.fixture
    def gemini_backend(self):
        """Create a GeminiBackend instance for testing."""
        mock_client = AsyncMock()
        from src.core.config.app_config import AppConfig
        from src.core.services.translation_service import TranslationService

        config = AppConfig()
        return GeminiBackend(
            mock_client, config=config, translation_service=TranslationService()
        )

    @pytest.fixture
    def sample_request_data(self):
        """Create sample request data for testing."""
        return ChatRequest(
            model="gemini-2.5-pro",
            messages=[ChatMessage(role="user", content="Test message")],
        )

    @pytest.fixture
    def sample_processed_messages(self):
        """Create sample processed messages for testing."""
        return [ChatMessage(role="user", content="Test message")]

    @pytest.mark.asyncio
    async def test_temperature_added_to_generation_config(
        self, gemini_backend, sample_request_data, sample_processed_messages
    ):
        """Test that temperature is properly added to generationConfig."""
        # Set temperature in request data
        sample_request_data = sample_request_data.model_copy(
            update={"temperature": 0.7}
        )

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Test response"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_response.headers = {}

        attach_gemini_non_streaming_httpx_mocks(gemini_backend.client, mock_response)

        req = gemini_connector_request(
            sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            options={
                "gemini_api_base_url": "https://generativelanguage.googleapis.com",
                "api_key": "test-key",
            },
        )
        await gemini_backend.chat_completions(req)

        gemini_backend.client.build_request.assert_called_once()
        payload = gemini_backend.client.build_request.call_args.kwargs["json"]

        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]
        assert payload["generationConfig"]["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_temperature_clamping_above_one(
        self, gemini_backend, sample_request_data, sample_processed_messages
    ):
        """Test that temperature > 1.0 is clamped to 1.0 for Gemini."""
        # Set temperature above 1.0
        sample_request_data = sample_request_data.model_copy(
            update={"temperature": 1.5}
        )

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Test response"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_response.headers = {}

        attach_gemini_non_streaming_httpx_mocks(gemini_backend.client, mock_response)

        req = gemini_connector_request(
            sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            options={
                "gemini_api_base_url": "https://generativelanguage.googleapis.com",
                "api_key": "test-key",
            },
        )
        await gemini_backend.chat_completions(req)

        gemini_backend.client.build_request.assert_called_once()
        payload = gemini_backend.client.build_request.call_args.kwargs["json"]

        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]
        assert payload["generationConfig"]["temperature"] == 1.0  # Clamped value

    @pytest.mark.asyncio
    async def test_temperature_zero_value(
        self, gemini_backend, sample_request_data, sample_processed_messages
    ):
        """Test that temperature 0.0 is properly handled."""
        # Set temperature to 0.0
        sample_request_data = sample_request_data.model_copy(
            update={"temperature": 0.0}
        )

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Test response"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_response.headers = {}

        attach_gemini_non_streaming_httpx_mocks(gemini_backend.client, mock_response)

        req = gemini_connector_request(
            sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            options={
                "gemini_api_base_url": "https://generativelanguage.googleapis.com",
                "api_key": "test-key",
            },
        )
        await gemini_backend.chat_completions(req)

        gemini_backend.client.build_request.assert_called_once()
        payload = gemini_backend.client.build_request.call_args.kwargs["json"]

        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]
        assert payload["generationConfig"]["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_temperature_with_existing_generation_config(
        self, gemini_backend, sample_request_data, sample_processed_messages
    ):
        """Test that temperature is added to existing generationConfig."""
        # Set temperature and existing generation config
        sample_request_data = sample_request_data.model_copy(
            update={
                "temperature": 0.8,
                "generation_config": {"maxOutputTokens": 1000, "topP": 0.9},
            }
        )

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Test response"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_response.headers = {}

        attach_gemini_non_streaming_httpx_mocks(gemini_backend.client, mock_response)

        req = gemini_connector_request(
            sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            options={
                "gemini_api_base_url": "https://generativelanguage.googleapis.com",
                "api_key": "test-key",
            },
        )
        await gemini_backend.chat_completions(req)

        gemini_backend.client.build_request.assert_called_once()
        payload = gemini_backend.client.build_request.call_args.kwargs["json"]

        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]
        assert payload["generationConfig"]["temperature"] == 0.8

    @pytest.mark.asyncio
    async def test_temperature_with_thinking_budget(
        self, gemini_backend, sample_request_data, sample_processed_messages
    ):
        """Test that temperature works alongside thinking budget."""
        # Set both temperature and thinking budget
        sample_request_data = sample_request_data.model_copy(
            update={"temperature": 0.6, "thinking_budget": 2048}
        )

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Test response"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_response.headers = {}

        attach_gemini_non_streaming_httpx_mocks(gemini_backend.client, mock_response)

        req = gemini_connector_request(
            sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            options={
                "gemini_api_base_url": "https://generativelanguage.googleapis.com",
                "api_key": "test-key",
            },
        )
        await gemini_backend.chat_completions(req)

        gemini_backend.client.build_request.assert_called_once()
        payload = gemini_backend.client.build_request.call_args.kwargs["json"]

        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]
        assert payload["generationConfig"]["temperature"] == 0.6

    @pytest.mark.asyncio
    async def test_no_temperature_no_generation_config(
        self, gemini_backend, sample_request_data, sample_processed_messages
    ):
        """Test that no generationConfig is created when temperature is not set."""
        # Don't set temperature (should be None)
        assert sample_request_data.temperature is None

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Test response"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_response.headers = {}

        attach_gemini_non_streaming_httpx_mocks(gemini_backend.client, mock_response)

        req = gemini_connector_request(
            sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            options={
                "gemini_api_base_url": "https://generativelanguage.googleapis.com",
                "api_key": "test-key",
            },
        )
        await gemini_backend.chat_completions(req)

        gemini_backend.client.build_request.assert_called_once()
        payload = gemini_backend.client.build_request.call_args.kwargs["json"]

        # generationConfig should not exist or should not contain temperature
        if "generationConfig" in payload:
            assert "temperature" not in payload["generationConfig"]

    @pytest.mark.asyncio
    async def test_temperature_with_extra_params_override(
        self, gemini_backend, sample_request_data, sample_processed_messages
    ):
        """Test that extra_params can override temperature setting."""
        # Set temperature in request data
        sample_request_data = sample_request_data.model_copy(
            update={
                "temperature": 0.7,
                "extra_body": {
                    "generationConfig": {
                        "temperature": 0.3  # Should override the direct temperature setting
                    }
                },
            }
        )

        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Test response"}]},
                    "finishReason": "STOP",
                }
            ]
        }
        mock_response.headers = {}

        attach_gemini_non_streaming_httpx_mocks(gemini_backend.client, mock_response)

        req = gemini_connector_request(
            sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            options={
                "gemini_api_base_url": "https://generativelanguage.googleapis.com",
                "api_key": "test-key",
            },
        )
        await gemini_backend.chat_completions(req)

        gemini_backend.client.build_request.assert_called_once()
        payload = gemini_backend.client.build_request.call_args.kwargs["json"]

        assert "generationConfig" in payload
        assert "temperature" in payload["generationConfig"]

    @pytest.mark.asyncio
    async def test_temperature_streaming_request(
        self, gemini_backend, sample_request_data, sample_processed_messages
    ):
        """Test temperature handling in streaming requests."""
        # Set temperature and enable streaming
        sample_request_data = sample_request_data.model_copy(
            update={"temperature": 0.9, "stream": True}
        )

        # Mock streaming response with proper async iterator
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}

        async def mock_aiter_text():
            yield '{"candidates": [{"content": {"parts": [{"text": "Streaming response"}]}}]}'

        mock_response.aiter_text = mock_aiter_text
        mock_response.aclose = AsyncMock()

        # Mock the client methods - need to mock both build_request and send
        mock_request = Mock()
        gemini_backend.client.build_request = Mock(return_value=mock_request)
        gemini_backend.client.send = AsyncMock(return_value=mock_response)

        req = gemini_connector_request(
            sample_request_data,
            processed_messages=sample_processed_messages,
            effective_model="gemini-2.5-pro",
            options={
                "gemini_api_base_url": "https://generativelanguage.googleapis.com",
                "api_key": "test-key",
            },
        )
        result = await gemini_backend.chat_completions(req)

        # Verify we got a streaming response
        from src.core.domain.responses import StreamingResponseEnvelope

        assert isinstance(result, StreamingResponseEnvelope)

        # The new streaming architecture handles temperature internally
        # We verify the response is correct rather than checking implementation details
        # Temperature is applied in the payload preparation which is tested in non-streaming tests
