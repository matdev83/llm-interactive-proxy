"""Tests for OpenAI Responses API connector."""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import httpx
import pytest
from pydantic.types import JsonValue
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorResponsesRequest,
)
from src.connectors.openai_responses import OpenAIResponsesConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
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
        connector.disable_health_check()
        return connector

    def _make_connector_request(
        self,
        connector: OpenAIResponsesConnector,
        request_data: CanonicalChatRequest | dict[str, object],
        *,
        processed_messages: list[ChatMessage] | None = None,
        effective_model: str = "gpt-4",
        options: dict[str, JsonValue] | None = None,
    ) -> ConnectorChatCompletionsRequest:
        if isinstance(request_data, CanonicalChatRequest):
            domain_request = request_data
        else:
            domain_request = connector.translation_service.to_domain_request(
                request_data, "responses"
            )
        return ConnectorChatCompletionsRequest(
            request=domain_request,
            processed_messages=processed_messages or [],
            effective_model=effective_model,
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options=options or {},
        )

    def _make_responses_connector_request(
        self,
        connector: OpenAIResponsesConnector,
        request_data: CanonicalChatRequest | dict[str, object],
        *,
        processed_messages: list[ChatMessage] | None = None,
        effective_model: str = "gpt-4",
        options: dict[str, JsonValue] | None = None,
    ) -> ConnectorResponsesRequest:
        return ConnectorResponsesRequest.from_chat_completions(
            self._make_connector_request(
                connector,
                request_data,
                processed_messages=processed_messages,
                effective_model=effective_model,
                options=options,
            )
        )

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
        mock_response.aread = AsyncMock()
        mock_client.build_request = MagicMock(return_value=MagicMock())
        mock_client.send = AsyncMock(return_value=mock_response)

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
            self._make_responses_connector_request(connector, request_data)
        )

        # Verify the result
        assert isinstance(result, ResponseEnvelope)
        assert result.status_code == 200
        assert "choices" in result.content
        assert len(result.content["choices"]) == 1

        mock_client.build_request.assert_called_once()
        call_args = mock_client.build_request.call_args
        assert call_args[0][1] == "https://api.openai.com/v1/responses"

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
        mock_response.headers = {}
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
            self._make_responses_connector_request(connector, request_data)
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
        mock_response.aread = AsyncMock()
        mock_client.build_request = MagicMock(return_value=MagicMock())
        mock_client.send = AsyncMock(return_value=mock_response)

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
            self._make_responses_connector_request(
                connector,
                request_data,
                processed_messages=processed_messages,
            )
        )

        # Verify the result
        assert isinstance(result, ResponseEnvelope)
        assert result.status_code == 200

        mock_client.build_request.assert_called_once()
        payload = mock_client.build_request.call_args[1]["json"]
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
        mock_response.aread = AsyncMock()
        mock_client.build_request = MagicMock(return_value=MagicMock())
        mock_client.send = AsyncMock(return_value=mock_response)

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
            self._make_responses_connector_request(
                connector,
                request_data,
                options={"headers_override": headers_override},
            )
        )

        assert isinstance(result, ResponseEnvelope)
        mock_client.build_request.assert_called_once()
        sent_headers = mock_client.build_request.call_args[1]["headers"]
        assert sent_headers["Authorization"] == "Bearer test-api-key"
        assert sent_headers["X-Test"] == "123"

        from src.core.security.loop_prevention import (
            LOOP_GUARD_HEADER,
            LOOP_GUARD_VALUE,
        )

        assert sent_headers[LOOP_GUARD_HEADER] == LOOP_GUARD_VALUE
        assert headers_override == {"X-Test": "123"}

    @pytest.mark.asyncio
    async def test_responses_error_handling(self, connector, mock_client):
        """Test error handling in Responses API calls."""
        # Mock an error response
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.headers = {}
        mock_response.json.return_value = {
            "error": {"message": "Invalid request", "type": "invalid_request_error"}
        }
        mock_response.aread = AsyncMock()
        mock_client.build_request = MagicMock(return_value=MagicMock())
        mock_client.send = AsyncMock(return_value=mock_response)

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

        from src.core.common.exceptions import BackendError

        with pytest.raises(BackendError) as exc_info:
            await connector.responses(
                self._make_responses_connector_request(connector, request_data)
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_chat_completions_delegates_to_responses(self, connector):
        """Test that chat_completions delegates to responses method."""
        with patch.object(
            connector, "responses", new_callable=AsyncMock
        ) as mock_responses:
            mock_responses.return_value = Mock(spec=ResponseEnvelope)

            domain = CanonicalChatRequest(
                model="gpt-4",
                messages=[ChatMessage(role="user", content="hi")],
            )
            connector_req = ConnectorChatCompletionsRequest(
                request=domain,
                processed_messages=[],
                effective_model="gpt-4",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )

            await connector.chat_completions(connector_req)

            mock_responses.assert_called_once_with(
                ConnectorResponsesRequest.from_chat_completions(connector_req)
            )

    def test_backend_type(self, connector):
        """Test that the backend type is correctly set."""
        assert connector.backend_type == "openai-responses"
