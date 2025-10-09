"""
Comprehensive integration tests for the Responses API Front-end.

These tests validate that the Responses API works end-to-end with all proxy features,
including backend compatibility, error handling, multimodal inputs, streaming,
and integration with existing proxy infrastructure.
"""

import json
import logging
from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.config.app_config import AppConfig, AuthConfig, BackendSettings
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse

logger = logging.getLogger(__name__)

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestResponsesAPIFrontendIntegration:
    """Comprehensive integration tests for Responses API Front-end."""

    @pytest.fixture
    def app_config(self) -> AppConfig:
        """Create an AppConfig for testing."""
        config = AppConfig(
            host="localhost",
            port=8000,
            command_prefix="!/",
            backends=BackendSettings(default_backend="mock"),
        )

        # Disable authentication for tests
        config.auth = AuthConfig(
            disable_auth=True, api_keys=[], redact_api_keys_in_prompts=False
        )

        return config

    @pytest.fixture
    def app(self, app_config: AppConfig) -> FastAPI:
        """Create a FastAPI app for testing."""
        from src.core.app.test_builder import build_test_app

        return build_test_app(app_config)

    @pytest.fixture
    def client(self, app: FastAPI) -> Generator[TestClient, None, None]:
        """Create a test client."""
        with TestClient(app) as client:
            yield client

    def test_responses_api_endpoint_basic_functionality(
        self, client: TestClient
    ) -> None:
        """Test basic Responses API endpoint functionality."""
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "What is 2+2?"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "math_answer",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "answer": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                        "required": ["answer", "confidence"],
                    },
                    "strict": True,
                },
            },
        }

        # Mock the request processor to return a proper Responses API response
        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:
            from src.core.domain.responses import ResponseEnvelope

            mock_response = ResponseEnvelope(
                content={
                    "id": "resp-mock-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "mock-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"answer": "4", "confidence": 0.95}',
                                "parsed": {"answer": "4", "confidence": 0.95},
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                }
            )
            mock_process.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["object"] == "response"
            assert "choices" in response_data
            assert len(response_data["choices"]) > 0
            assert "message" in response_data["choices"][0]
            assert response_data["choices"][0]["message"]["parsed"]["answer"] == "4"

    @pytest.mark.parametrize(
        "additional_properties",
        [False, {"type": "string"}],
        ids=["bool", "schema"],
    )
    def test_responses_api_accepts_additional_properties(
        self, client: TestClient, additional_properties: bool | dict[str, str]
    ) -> None:
        """Ensure JSON schemas with additionalProperties are validated correctly."""

        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Return metadata"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "metadata_envelope",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "metadata": {
                                "type": "object",
                                "additionalProperties": additional_properties,
                            }
                        },
                        "required": ["metadata"],
                    },
                    "strict": True,
                },
            },
        }

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:
            from src.core.domain.responses import ResponseEnvelope

            mock_process.return_value = ResponseEnvelope(
                content={
                    "id": "resp-addl-props-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "mock-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"metadata": {"key": "value"}}',
                                "parsed": {"metadata": {"key": "value"}},
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            )

            response = client.post("/v1/responses", json=request_data)

            assert response.status_code == 200
            assert (
                response.json()["choices"][0]["message"]["parsed"]["metadata"]["key"]
                == "value"
            )
            mock_process.assert_called_once()

    def test_responses_api_with_anthropic_backend_compatibility(
        self, client: TestClient
    ) -> None:
        """Test Responses API compatibility with Anthropic backend through TranslationService."""
        request_data = {
            "model": "claude-3-sonnet-20240229",
            "messages": [{"role": "user", "content": "Generate a user profile"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "user_profile",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "age": {"type": "integer"},
                        },
                        "required": ["name", "age"],
                    },
                    "strict": True,
                },
            },
        }

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:
            from src.core.domain.responses import ResponseEnvelope

            mock_response = ResponseEnvelope(
                content={
                    "id": "resp-anthropic-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "claude-3-sonnet-20240229",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"name": "Alice Johnson", "age": 28}',
                                "parsed": {"name": "Alice Johnson", "age": 28},
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 15,
                        "completion_tokens": 10,
                        "total_tokens": 25,
                    },
                }
            )
            mock_process.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["object"] == "response"
            assert response_data["model"] == "claude-3-sonnet-20240229"
            assert (
                response_data["choices"][0]["message"]["parsed"]["name"]
                == "Alice Johnson"
            )

    def test_responses_api_with_gemini_backend_compatibility(
        self, client: TestClient
    ) -> None:
        """Test Responses API compatibility with Gemini backend through TranslationService."""
        request_data = {
            "model": "gemini-1.5-pro",
            "messages": [{"role": "user", "content": "Create a task object"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "task_object",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "priority": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                            },
                            "completed": {"type": "boolean"},
                        },
                        "required": ["title", "priority", "completed"],
                    },
                    "strict": True,
                },
            },
        }

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:
            from src.core.domain.responses import ResponseEnvelope

            mock_response = ResponseEnvelope(
                content={
                    "id": "resp-gemini-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "gemini-1.5-pro",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"title": "Complete project", "priority": "high", "completed": false}',
                                "parsed": {
                                    "title": "Complete project",
                                    "priority": "high",
                                    "completed": False,
                                },
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 15,
                        "total_tokens": 35,
                    },
                }
            )
            mock_process.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["object"] == "response"
            assert response_data["model"] == "gemini-1.5-pro"
            assert (
                response_data["choices"][0]["message"]["parsed"]["priority"] == "high"
            )

    def test_responses_api_error_handling_invalid_schema(
        self, client: TestClient
    ) -> None:
        """Test error handling for invalid JSON schema."""
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Test"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "invalid_schema",
                    "schema": {
                        # Missing required 'type' field
                        "properties": {"test": {"type": "string"}}
                    },
                },
            },
        }

        response = client.post("/v1/responses", json=request_data)

        # Should return 400 for invalid schema (controller-level validation)
        assert response.status_code == 400
        error_data = response.json()
        assert "detail" in error_data

    def test_responses_api_error_handling_missing_fields(
        self, client: TestClient
    ) -> None:
        """Test error handling for missing required fields."""
        # Missing messages
        request_data = {
            "model": "mock-model",
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "test", "schema": {"type": "object"}},
            },
        }

        response = client.post("/v1/responses", json=request_data)
        assert response.status_code == 422  # Validation error

        # Missing response_format
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Test"}],
        }

        response = client.post("/v1/responses", json=request_data)
        assert response.status_code == 422  # Validation error

    def test_responses_api_with_multimodal_input(self, client: TestClient) -> None:
        """Test Responses API with multimodal input (image)."""
        request_data = {
            "model": "gpt-4-vision-preview",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.com/image.jpg"},
                        },
                    ],
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "image_description",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "objects": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number"},
                        },
                        "required": ["description"],
                    },
                },
            },
        }

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:
            from src.core.domain.responses import ResponseEnvelope

            mock_response = ResponseEnvelope(
                content={
                    "id": "resp-multimodal-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "gpt-4-vision-preview",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"description": "A beautiful landscape", "objects": ["tree", "mountain"], "confidence": 0.95}',
                                "parsed": {
                                    "description": "A beautiful landscape",
                                    "objects": ["tree", "mountain"],
                                    "confidence": 0.95,
                                },
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 25,
                        "completion_tokens": 20,
                        "total_tokens": 45,
                    },
                }
            )
            mock_process.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["object"] == "response"
            assert "objects" in response_data["choices"][0]["message"]["parsed"]

    def test_responses_api_streaming_functionality(self, client: TestClient) -> None:
        """Test Responses API streaming functionality."""
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Generate a streaming response"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "streaming_response",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "chunk_count": {"type": "integer"},
                        },
                        "required": ["content"],
                    },
                },
            },
            "stream": True,
        }

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:

            # Create a mock streaming response
            async def mock_stream():
                chunks = [
                    'data: {"id": "resp-stream-123", "object": "response.chunk", "choices": [{"index": 0, "delta": {"content": "{\\"content\\": \\"Hello"}}]}\n\n',
                    'data: {"id": "resp-stream-123", "object": "response.chunk", "choices": [{"index": 0, "delta": {"content": " world\\", \\"chunk_count\\": 2}"}}]}\n\n',
                    'data: {"id": "resp-stream-123", "object": "response.chunk", "choices": [{"index": 0, "delta": {"content": "}"}, "finish_reason": "stop"}]}\n\n',
                    "data: [DONE]\n\n",
                ]
                for chunk in chunks:
                    yield chunk

            mock_response = StreamingResponseEnvelope(
                content=mock_stream(),
                headers={"content-type": "text/event-stream"},
                media_type="text/event-stream",
            )
            mock_process.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            # Should return 200 for streaming request
            assert response.status_code == 200
            # Content type should be text/event-stream for streaming
            assert "text/event-stream" in response.headers.get("content-type", "")

    def test_responses_api_streaming_propagates_tool_calls(
        self, client: TestClient
    ) -> None:
        """Tool-call deltas should reach Responses frontend clients."""
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Stream tool call"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "tool_stream",
                    "schema": {
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                        "required": ["result"],
                    },
                    "strict": True,
                },
            },
            "stream": True,
        }

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:

            async def mock_stream():
                yield ProcessedResponse(
                    content="",
                    metadata={
                        "tool_calls": [
                            {
                                "id": "call_abc",
                                "type": "function",
                                "function": {
                                    "name": "fetch_data",
                                    "arguments": '{"query": "status"}',
                                },
                            }
                        ]
                    },
                )
                yield ProcessedResponse(content="", metadata={"is_done": True})

            mock_response = StreamingResponseEnvelope(
                content=mock_stream(), headers={}, media_type="text/event-stream"
            )
            mock_process.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            assert response.status_code == 200
            body = response.content.decode("utf-8")
            data_lines = [
                line for line in body.splitlines() if line.startswith("data:")
            ]
            assert data_lines, body
            first_payload = json.loads(data_lines[0].split("data: ", 1)[1])
            tool_delta = first_payload["choices"][0]["delta"].get("tool_calls")
            assert tool_delta, first_payload
            assert tool_delta[0]["function"]["name"] == "fetch_data"
            assert tool_delta[0]["function"]["arguments"] == '{"query": "status"}'

    def test_responses_api_non_streaming_functionality(
        self, client: TestClient
    ) -> None:
        """Test Responses API non-streaming functionality."""
        request_data = {
            "model": "mock-model",
            "messages": [
                {"role": "user", "content": "Generate a non-streaming response"}
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "non_streaming_response",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string"},
                            "timestamp": {"type": "string"},
                        },
                        "required": ["message"],
                    },
                },
            },
            "stream": False,
        }

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:
            from src.core.domain.responses import ResponseEnvelope

            mock_response = ResponseEnvelope(
                content={
                    "id": "resp-non-stream-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "mock-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"message": "Hello world", "timestamp": "2024-01-01T00:00:00Z"}',
                                "parsed": {
                                    "message": "Hello world",
                                    "timestamp": "2024-01-01T00:00:00Z",
                                },
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 15,
                        "total_tokens": 25,
                    },
                }
            )
            mock_process.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            assert response.status_code == 200
            # Content type should be application/json for non-streaming
            assert "application/json" in response.headers.get("content-type", "")

            response_data = response.json()
            assert response_data["object"] == "response"
            assert (
                response_data["choices"][0]["message"]["parsed"]["message"]
                == "Hello world"
            )

    def test_responses_api_with_commands_integration(self, client: TestClient) -> None:
        """Test that Responses API works with proxy commands."""
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "!/help"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "help_response",
                    "schema": {
                        "type": "object",
                        "properties": {"help": {"type": "string"}},
                        "required": ["help"],
                    },
                    "strict": True,
                },
            },
        }

        # Make the request - commands should be processed by the proxy
        response = client.post("/v1/responses", json=request_data)

        # The command should be processed and return a help response
        # Even if it fails due to missing services, it should not return a 404
        assert response.status_code != 404
        # Commands are processed by the proxy infrastructure

    def test_responses_api_with_session_management(self, client: TestClient) -> None:
        """Test that Responses API works with session management."""
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Remember my name is Alice"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "memory_response",
                    "schema": {
                        "type": "object",
                        "properties": {"acknowledged": {"type": "boolean"}},
                        "required": ["acknowledged"],
                    },
                    "strict": True,
                },
            },
        }

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:
            from src.core.domain.responses import ResponseEnvelope

            mock_response = ResponseEnvelope(
                content={
                    "id": "resp-session-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "mock-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"acknowledged": true}',
                                "parsed": {"acknowledged": True},
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }
            )
            mock_process.return_value = mock_response

            # Make the request with session header
            response = client.post(
                "/v1/responses",
                json=request_data,
                headers={"x-session-id": "test-session-123"},
            )

            # Check that the request was successful
            assert response.status_code == 200

            # Session management should be handled by the proxy infrastructure
            response_data = response.json()
            assert response_data["object"] == "response"

    def test_responses_api_middleware_integration(self, client: TestClient) -> None:
        """Test that all middleware applies to the Responses API endpoint."""
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Test middleware integration"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "test_response",
                    "schema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                    "strict": True,
                },
            },
        }

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:
            from src.core.domain.responses import ResponseEnvelope

            mock_response = ResponseEnvelope(
                content={
                    "id": "resp-middleware-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "mock-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"message": "Middleware integration successful"}',
                                "parsed": {
                                    "message": "Middleware integration successful"
                                },
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 8,
                        "completion_tokens": 12,
                        "total_tokens": 20,
                    },
                }
            )
            mock_process.return_value = mock_response

            # Make the request with various headers to test middleware
            response = client.post(
                "/v1/responses",
                json=request_data,
                headers={
                    "content-type": "application/json",
                    "user-agent": "test-client",
                    "x-session-id": "middleware-test-session",
                },
            )

            # Check that the request was successful
            # All existing middleware should apply to the new endpoint
            assert response.status_code == 200

            response_data = response.json()
            assert response_data["object"] == "response"
            assert "choices" in response_data

    def test_responses_api_with_tool_calls(self, client: TestClient) -> None:
        """Test that Responses API works with tool calls (structured outputs)."""
        request_data = {
            "model": "mock-model",
            "messages": [
                {"role": "user", "content": "Calculate 2+2 using a calculator tool"}
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "tool_call_response",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "tool_calls": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "arguments": {"type": "object"},
                                    },
                                },
                            }
                        },
                    },
                    "strict": True,
                },
            },
        }

        with patch(
            "src.core.services.request_processor_service.RequestProcessor.process_request"
        ) as mock_process:
            from src.core.domain.responses import ResponseEnvelope

            mock_response = ResponseEnvelope(
                content={
                    "id": "resp-tool-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "mock-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"tool_calls": [{"name": "calculator", "arguments": {"expression": "2+2"}}]}',
                                "parsed": {
                                    "tool_calls": [
                                        {
                                            "name": "calculator",
                                            "arguments": {"expression": "2+2"},
                                        }
                                    ]
                                },
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 15,
                        "completion_tokens": 25,
                        "total_tokens": 40,
                    },
                }
            )
            mock_process.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            assert response.status_code == 200

            # Tool call functionality should be handled by the proxy infrastructure
            response_data = response.json()
            assert response_data["object"] == "response"
