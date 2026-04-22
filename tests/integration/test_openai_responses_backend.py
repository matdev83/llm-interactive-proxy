"""Integration tests for OpenAI Responses API backend connector."""

from unittest.mock import AsyncMock, Mock

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
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService


def _configure_non_streaming_http_mocks(
    mock_client: AsyncMock, mock_response: Mock
) -> None:
    """Wire mocks for CaptureAwareAsyncClient path (build_request + send + aread)."""
    mock_response.aread = AsyncMock()
    mock_client.build_request = Mock(return_value=Mock(spec=httpx.Request))
    mock_client.send = AsyncMock(return_value=mock_response)


def _build_connector_request(
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


def _build_responses_connector_request(
    connector: OpenAIResponsesConnector,
    request_data: CanonicalChatRequest | dict[str, object],
    *,
    processed_messages: list[ChatMessage] | None = None,
    effective_model: str = "gpt-4",
    options: dict[str, JsonValue] | None = None,
) -> ConnectorResponsesRequest:
    return ConnectorResponsesRequest.from_chat_completions(
        _build_connector_request(
            connector,
            request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
            options=options,
        )
    )


class TestOpenAIResponsesBackendIntegration:
    """Integration tests for OpenAI Responses API backend."""

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
        # Disable health checks for testing
        connector.disable_health_check()
        return connector

    def test_backend_registration(self):
        """Test that the OpenAI Responses API backend is properly registered."""
        registered_backends = backend_registry.get_registered_backends()
        assert "openai-responses" in registered_backends

        factory = backend_registry.get_backend_factory("openai-responses")
        assert factory == OpenAIResponsesConnector

    @pytest.mark.asyncio
    async def test_end_to_end_responses_api_call(self, connector, mock_client):
        """Test end-to-end Responses API call with full translation pipeline."""
        # Mock successful OpenAI Responses API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "id": "resp-abc123",
            "object": "response",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": '{"name": "Alice Smith", "age": 28, "email": "alice@example.com"}',
                        "parsed": {
                            "name": "Alice Smith",
                            "age": 28,
                            "email": "alice@example.com",
                        },
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 25, "completion_tokens": 15, "total_tokens": 40},
        }
        _configure_non_streaming_http_mocks(mock_client, mock_response)

        # Create a Responses API request
        request_data = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": "Generate a person profile with name, age, and email",
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "person_profile",
                    "description": "A person's basic profile information",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "age": {"type": "integer", "minimum": 0},
                            "email": {"type": "string", "format": "email"},
                        },
                        "required": ["name", "age", "email"],
                        "additionalProperties": False,
                    },
                    "strict": True,
                },
            },
            "max_tokens": 100,
            "temperature": 0.7,
        }

        # Execute the request
        result = await connector.responses(
            _build_responses_connector_request(connector, request_data)
        )

        # Verify the result
        assert isinstance(result, ResponseEnvelope)
        assert result.status_code == 200

        # Verify response content structure
        content = result.content
        assert content["id"] == "resp-abc123"
        assert content["object"] == "response"
        assert content["model"] == "gpt-4"
        assert len(content["choices"]) == 1

        choice = content["choices"][0]
        assert choice["index"] == 0
        assert choice["message"]["role"] == "assistant"
        assert choice["message"]["parsed"] is not None
        assert choice["message"]["parsed"]["name"] == "Alice Smith"
        assert choice["message"]["parsed"]["age"] == 28
        assert choice["finish_reason"] == "stop"

        # Verify the HTTP call was made correctly
        mock_client.build_request.assert_called_once()
        bcall = mock_client.build_request.call_args
        assert bcall.args[0] == "POST"
        assert str(bcall.args[1]).rstrip("/").endswith("/responses")

        # Verify request payload
        payload = bcall.kwargs["json"]
        assert payload["model"] == "gpt-4"
        assert "response_format" in payload
        assert payload["response_format"]["type"] == "json_schema"
        assert payload["response_format"]["json_schema"]["name"] == "person_profile"

    @pytest.mark.asyncio
    async def test_responses_api_with_different_frontend_formats(
        self, connector, mock_client
    ):
        """Test that the backend works with requests translated from different frontend formats."""
        # Mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "id": "resp-xyz789",
            "object": "response",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": '{"status": "success", "data": {"count": 42}}',
                        "parsed": {"status": "success", "data": {"count": 42}},
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        _configure_non_streaming_http_mocks(mock_client, mock_response)

        # Simulate a request that came from Anthropic frontend but needs structured output
        anthropic_style_request = {
            "model": "claude-3-sonnet-20240229",
            "messages": [
                {"role": "user", "content": "Count something and return the result"}
            ],
            "max_tokens": 50,
        }

        # Create domain request directly with structured output
        from src.core.domain.chat import ChatMessage

        extra_body = {
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "count_result",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string"},
                            "data": {
                                "type": "object",
                                "properties": {"count": {"type": "integer"}},
                            },
                        },
                    },
                },
            }
        }

        domain_request = CanonicalChatRequest(
            model=anthropic_style_request["model"],
            messages=[
                ChatMessage(**msg) for msg in anthropic_style_request["messages"]
            ],
            max_tokens=anthropic_style_request["max_tokens"],
            extra_body=extra_body,
        )

        # Convert to Responses API backend format
        translation_service = TranslationService()
        backend_request = translation_service.from_domain_request(
            domain_request, "openai-responses"
        )

        # Execute the request
        result = await connector.responses(
            _build_responses_connector_request(connector, backend_request)
        )

        # Verify the result
        assert isinstance(result, ResponseEnvelope)
        assert result.status_code == 200

        content = result.content
        assert content["choices"][0]["message"]["parsed"]["status"] == "success"
        assert content["choices"][0]["message"]["parsed"]["data"]["count"] == 42

    @pytest.mark.asyncio
    async def test_responses_api_streaming(self, connector, mock_client):
        """Test streaming Responses API calls."""
        # Mock streaming response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}

        # Simulate streaming chunks
        streaming_chunks = [
            'data: {"id": "resp-stream123", "object": "response.chunk", "created": 1234567890, "model": "gpt-4", "choices": [{"index": 0, "delta": {"content": "{"}, "finish_reason": null}]}\n\n',
            'data: {"id": "resp-stream123", "object": "response.chunk", "created": 1234567890, "model": "gpt-4", "choices": [{"index": 0, "delta": {"content": "\\"result\\""}, "finish_reason": null}]}\n\n',
            'data: {"id": "resp-stream123", "object": "response.chunk", "created": 1234567890, "model": "gpt-4", "choices": [{"index": 0, "delta": {"content": ": \\"success\\""}, "finish_reason": null}]}\n\n',
            'data: {"id": "resp-stream123", "object": "response.chunk", "created": 1234567890, "model": "gpt-4", "choices": [{"index": 0, "delta": {"content": "}"}, "finish_reason": "stop"}]}\n\n',
            "data: [DONE]\n\n",
        ]

        async def mock_aiter_bytes():
            for chunk in streaming_chunks:
                yield chunk.encode("utf-8")

        mock_response.aiter_bytes = Mock(return_value=mock_aiter_bytes())
        mock_response.aclose = AsyncMock()

        mock_client.build_request.return_value = Mock()
        mock_client.send.return_value = mock_response

        # Create streaming request
        request_data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Generate a result"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "simple_result",
                    "schema": {
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                    },
                },
            },
            "stream": True,
        }

        # Execute streaming request
        result = await connector.responses(
            _build_responses_connector_request(connector, request_data)
        )

        # Verify streaming response
        assert isinstance(result, StreamingResponseEnvelope)
        assert result.media_type == "text/event-stream"

        # Verify we can iterate through the content
        chunks = []
        async for chunk in result.content:
            chunks.append(chunk)

        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_responses_api_error_handling(self, connector, mock_client):
        """Test error handling for Responses API calls."""
        # Test 400 Bad Request
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.headers = {}
        mock_response.json.return_value = {
            "error": {
                "message": "Invalid JSON schema provided",
                "type": "invalid_request_error",
                "code": "invalid_schema",
            }
        }
        _configure_non_streaming_http_mocks(mock_client, mock_response)

        request_data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "test"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "invalid",
                    "schema": {
                        "type": "object",
                        "invalid": "schema",
                    },  # Invalid but has required 'type' field
                },
            },
        }

        from src.core.common.exceptions import BackendError

        with pytest.raises(BackendError) as exc_info:
            await connector.responses(
                _build_responses_connector_request(connector, request_data)
            )

        assert exc_info.value.status_code == 400

        # Test 401 Unauthorized
        mock_response_401 = Mock()
        mock_response_401.status_code = 401
        mock_response_401.headers = {}
        mock_response_401.json.return_value = {
            "error": {"message": "Invalid API key", "type": "authentication_error"}
        }
        _configure_non_streaming_http_mocks(mock_client, mock_response_401)

        with pytest.raises(BackendError) as exc_info:
            await connector.responses(
                _build_responses_connector_request(connector, request_data)
            )

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_responses_api_with_processed_messages(self, connector, mock_client):
        """Test Responses API with processed messages from middleware."""
        # Mock response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {
            "id": "resp-processed123",
            "object": "response",
            "created": 1234567890,
            "model": "gpt-4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": '{"processed": true}',
                        "parsed": {"processed": True},
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        _configure_non_streaming_http_mocks(mock_client, mock_response)

        # Original request
        request_data = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Original message"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "processed_result",
                    "schema": {
                        "type": "object",
                        "properties": {"processed": {"type": "boolean"}},
                    },
                },
            },
        }

        # Processed messages (simulating middleware processing)
        processed_messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(
                role="user", content="Processed message with additional context"
            ),
        ]

        # Execute request
        result = await connector.responses(
            _build_responses_connector_request(
                connector,
                request_data,
                processed_messages=processed_messages,
            )
        )

        # Verify the result
        assert isinstance(result, ResponseEnvelope)
        assert result.status_code == 200

        # Verify that processed messages were used in the request
        mock_client.build_request.assert_called_once()
        payload = mock_client.build_request.call_args.kwargs["json"]

        # Should have 2 messages from processed_messages
        assert len(payload["messages"]) == 2
        assert payload["messages"][0]["role"] == "system"
        assert payload["messages"][0]["content"] == "You are a helpful assistant."
        assert payload["messages"][1]["role"] == "user"
        assert (
            payload["messages"][1]["content"]
            == "Processed message with additional context"
        )

    def test_backend_type_consistency(self, connector):
        """Test that backend type is consistent."""
        assert connector.backend_type == "openai-responses"

        # Verify it's different from base OpenAI connector
        from src.connectors.openai import OpenAIConnector

        base_connector = OpenAIConnector(
            client=Mock(), config=Mock(), translation_service=TranslationService()
        )
        assert base_connector.backend_type == "openai"
        assert connector.backend_type != base_connector.backend_type
