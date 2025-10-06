"""Tests for OpenAI Responses API connector."""

from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest
from src.connectors.openai_responses import OpenAIResponsesConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage
from src.core.domain.responses import ResponseEnvelope
from src.core.services.translation_service import TranslationService


class TestOpenAIResponsesConnector:
    """Test OpenAI Responses API connector."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock HTTP client."""
        client = AsyncMock(spec=httpx.AsyncClient)
        return client

    @pytest.fixture
    def mock_config(self):
        """Create a mock app config."""
        config = Mock(spec=AppConfig)
        return config

    @pytest.fixture
    def translation_service(self):
        """Create a translation service."""
        return TranslationService()

    @pytest.fixture
    def connector(self, mock_client, mock_config, translation_service):
        """Create an OpenAI Responses API connector."""
        connector = OpenAIResponsesConnector(
            client=mock_client,
            config=mock_config,
            translation_service=translation_service,
        )
        connector.api_key = "test-api-key"
        connector.api_base_url = "https://api.openai.com/v1"
        return connector

    @pytest.mark.asyncio
    async def test_responses_non_streaming(self, connector, mock_client):
        """Test non-streaming Responses API call."""
        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "id": "resp-123",
            "object": "response",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": '{"name": "John Doe"}',
                        "parsed": {"name": "John Doe"},
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
        mock_client.post.return_value = mock_response

        # Create request data
        request_data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Generate a person"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "person",
                    "schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                },
            },
        }

        # Call the responses method
        result = await connector.responses(
            request_data=request_data, processed_messages=[], effective_model="gpt-4"
        )

        # Verify the result
        assert isinstance(result, ResponseEnvelope)
        assert result.status_code == 200
        assert "choices" in result.content
        assert len(result.content["choices"]) == 1

        # Verify the HTTP call was made correctly
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        # Check positional arguments (URL) and keyword arguments
        assert call_args[0][0] == "https://api.openai.com/v1/responses"

        # Verify the payload structure
        payload = call_args[1]["json"]
        assert payload["model"] == "gpt-4"
        assert "response_format" in payload
        assert payload["response_format"]["type"] == "json_schema"

    @pytest.mark.asyncio
    async def test_responses_streaming(self, connector, mock_client):
        """Test streaming Responses API call."""
        # Mock the streaming response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.aiter_text = AsyncMock()
        mock_response.aiter_text.return_value = [
            'data: {"id": "resp-123", "object": "response.chunk", "choices": [{"delta": {"content": "{"}}]}\n\n',
            'data: {"id": "resp-123", "object": "response.chunk", "choices": [{"delta": {"content": "\\"name\\""}}]}\n\n',
            'data: {"id": "resp-123", "object": "response.chunk", "choices": [{"delta": {"content": ": \\"John\\""}}]}\n\n',
            'data: {"id": "resp-123", "object": "response.chunk", "choices": [{"delta": {"content": "}"}}]}\n\n',
            "data: [DONE]\n\n",
        ]
        mock_response.aclose = AsyncMock()

        mock_client.build_request.return_value = Mock()
        mock_client.send.return_value = mock_response

        # Create streaming request data
        request_data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Generate a person"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "person",
                    "schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                },
            },
            "stream": True,
        }

        # Call the responses method
        result = await connector.responses(
            request_data=request_data, processed_messages=[], effective_model="gpt-4"
        )

        # Verify it returns a streaming response
        from src.core.domain.responses import StreamingResponseEnvelope

        assert isinstance(result, StreamingResponseEnvelope)
        assert result.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_responses_with_processed_messages(self, connector, mock_client):
        """Test Responses API call with processed messages."""
        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "id": "resp-123",
            "object": "response",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": '{"name": "John Doe"}',
                        "parsed": {"name": "John Doe"},
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        mock_client.post.return_value = mock_response

        # Create request data
        request_data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Original message"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "person",
                    "schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                },
            },
        }

        # Create processed messages
        processed_message = ChatMessage(role="user", content="Processed message")
        processed_messages = [processed_message]

        # Call the responses method
        result = await connector.responses(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model="gpt-4",
        )

        # Verify the result
        assert isinstance(result, ResponseEnvelope)
        assert result.status_code == 200

        # Verify the processed messages were used
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        payload = call_args[1]["json"]
        assert len(payload["messages"]) == 1
        assert payload["messages"][0]["content"] == "Processed message"

    @pytest.mark.asyncio
    async def test_responses_headers_override_preserves_authorization(
        self, connector, mock_client
    ):
        """Ensure headers overrides merge with auth headers instead of replacing them."""

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "id": "resp-123",
            "object": "response",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "{}",
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        mock_client.post.return_value = mock_response

        request_data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Generate a person"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "person",
                    "schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                },
            },
        }

        headers_override = {"X-Test": "123"}

        result = await connector.responses(
            request_data=request_data,
            processed_messages=[],
            effective_model="gpt-4",
            headers_override=headers_override,
        )

        assert isinstance(result, ResponseEnvelope)
        mock_client.post.assert_called_once()
        sent_headers = mock_client.post.call_args[1]["headers"]
        assert sent_headers["Authorization"] == "Bearer test-api-key"
        assert sent_headers["X-Test"] == "123"

        from src.core.security.loop_prevention import LOOP_GUARD_HEADER, LOOP_GUARD_VALUE

        assert sent_headers[LOOP_GUARD_HEADER] == LOOP_GUARD_VALUE
        assert headers_override == {"X-Test": "123"}

    @pytest.mark.asyncio
    async def test_responses_error_handling(self, connector, mock_client):
        """Test error handling in Responses API calls."""
        # Mock an error response
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "error": {"message": "Invalid request", "type": "invalid_request_error"}
        }
        mock_client.post.return_value = mock_response

        # Create request data
        request_data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Generate a person"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "person",
                    "schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                },
            },
        }

        # Call the responses method and expect an exception
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await connector.responses(
                request_data=request_data,
                processed_messages=[],
                effective_model="gpt-4",
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_chat_completions_delegates_to_responses(self, connector):
        """Test that chat_completions delegates to responses method."""
        with patch.object(
            connector, "responses", new_callable=AsyncMock
        ) as mock_responses:
            mock_responses.return_value = Mock(spec=ResponseEnvelope)

            request_data = {"model": "gpt-4", "messages": []}
            processed_messages = []
            effective_model = "gpt-4"

            await connector.chat_completions(
                request_data=request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
            )

            mock_responses.assert_called_once_with(
                request_data, processed_messages, effective_model, None
            )

    def test_backend_type(self, connector):
        """Test that the backend type is correctly set."""
        assert connector.backend_type == "openai-responses"
