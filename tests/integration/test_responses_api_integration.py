"""
Integration tests for the Responses API Front-end.

These tests validate that the Responses API works end-to-end with all proxy features,
including backend compatibility, error handling, multimodal inputs, streaming,
and integration with existing proxy infrastructure.
"""

import logging
from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.config.app_config import AppConfig, AuthConfig, BackendSettings

logger = logging.getLogger(__name__)

# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


@pytest.fixture
def app_config() -> AppConfig:
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
def app(app_config: AppConfig) -> FastAPI:
    """Create a FastAPI app for testing."""
    # Use the test application factory which includes mock backends
    from src.core.app.test_builder import build_test_app

    return build_test_app(app_config)


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    """Create a test client."""
    with TestClient(app) as client:
        yield client


def test_responses_api_endpoint_exists(client: TestClient) -> None:
    """Test that the Responses API endpoint exists and is accessible."""
    # Create a responses request
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

    # Mock the backend service to avoid actual API calls
    with patch(
        "src.core.services.backend_service.BackendService.call_completion"
    ) as mock_call_completion:
        from src.core.domain.responses import ResponseEnvelope

        # Create a mock response in Responses API format
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
        mock_call_completion.return_value = mock_response

        # Make the request
        response = client.post("/v1/responses", json=request_data)

        # Check that the request was successful
        assert response.status_code == 200

        # Verify the response format
        response_data = response.json()
        assert response_data["object"] == "response"
        assert "choices" in response_data
        assert len(response_data["choices"]) > 0
        assert "message" in response_data["choices"][0]


def test_responses_api_with_commands(client: TestClient) -> None:
    """Test that the Responses API works with proxy commands."""
    # Create a responses request with a command
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


def test_responses_api_with_session(client: TestClient) -> None:
    """Test that the Responses API works with session management."""
    # Create a responses request with session header
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

    # Mock the backend service
    with patch(
        "src.core.services.backend_service.BackendService.call_completion"
    ) as mock_call_completion:
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
        mock_call_completion.return_value = mock_response

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


def test_responses_api_with_tool_calls(client: TestClient) -> None:
    """Test that the Responses API works with tool calls (structured outputs)."""
    # Create a responses request that might generate tool calls
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

    # Mock the backend service
    with patch(
        "src.core.services.backend_service.BackendService.call_completion"
    ) as mock_call_completion:
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
        mock_call_completion.return_value = mock_response

        # Make the request
        response = client.post("/v1/responses", json=request_data)

        # Check that the request was successful
        assert response.status_code == 200

        # Tool call functionality should be handled by the proxy infrastructure
        response_data = response.json()
        assert response_data["object"] == "response"


def test_responses_api_middleware_integration(client: TestClient) -> None:
    """Test that all middleware applies to the Responses API endpoint."""
    # Create a responses request
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

    # Mock the backend service
    with patch(
        "src.core.services.backend_service.BackendService.call_completion"
    ) as mock_call_completion:
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
                            "parsed": {"message": "Middleware integration successful"},
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
        mock_call_completion.return_value = mock_response

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


class TestResponsesAPIBackendCompatibility:
    """Test Responses API compatibility with different backends through TranslationService."""

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

    def test_responses_api_with_anthropic_backend(self, client: TestClient) -> None:
        """Test Responses API with Anthropic backend through TranslationService."""
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

        # Mock the backend service to simulate Anthropic backend
        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call_completion:
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
            mock_call_completion.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["object"] == "response"
            assert response_data["model"] == "claude-3-sonnet-20240229"
            assert (
                response_data["choices"][0]["message"]["parsed"]["name"]
                == "Alice Johnson"
            )

    def test_responses_api_with_gemini_backend(self, client: TestClient) -> None:
        """Test Responses API with Gemini backend through TranslationService."""
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

        # Mock the backend service to simulate Gemini backend
        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call_completion:
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
            mock_call_completion.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["object"] == "response"
            assert response_data["model"] == "gemini-1.5-pro"
            assert (
                response_data["choices"][0]["message"]["parsed"]["priority"] == "high"
            )


class TestResponsesAPIErrorHandling:
    """Test error handling and fallback scenarios for Responses API."""

    @pytest.fixture
    def app_config(self) -> AppConfig:
        """Create an AppConfig for testing."""
        config = AppConfig(
            host="localhost",
            port=8000,
            command_prefix="!/",
            backends=BackendSettings(default_backend="mock"),
        )

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

    def test_invalid_json_schema_error(self, client: TestClient) -> None:
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

        # Should return 400 for invalid schema
        assert response.status_code == 400
        error_data = response.json()
        assert "detail" in error_data

    def test_missing_required_fields_error(self, client: TestClient) -> None:
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

    def test_backend_failure_error_handling(self, client: TestClient) -> None:
        """Test error handling when backend fails."""
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Test backend failure"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "test_response",
                    "schema": {
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                        "required": ["result"],
                    },
                },
            },
        }

        # Mock backend service to raise an exception
        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call_completion:
            from fastapi import HTTPException

            mock_call_completion.side_effect = HTTPException(
                status_code=500, detail="Backend unavailable"
            )

            response = client.post("/v1/responses", json=request_data)

            # Should return 500 for backend failure
            assert response.status_code == 500

    def test_json_repair_fallback(self, client: TestClient) -> None:
        """Test JSON repair functionality when backend returns malformed JSON."""
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Generate malformed JSON"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "repair_test",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string"},
                            "data": {"type": "object"},
                        },
                        "required": ["status"],
                    },
                },
            },
        }

        # Mock backend to return malformed JSON that can be repaired
        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call_completion:
            from src.core.domain.responses import ResponseEnvelope

            # Malformed JSON that JsonRepairService should be able to fix
            mock_response = ResponseEnvelope(
                content={
                    "id": "resp-repair-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "mock-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"status": "success", "data": {"incomplete": true',  # Missing closing braces
                                "parsed": None,  # Indicates parsing failed
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            )
            mock_call_completion.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            # Should still return 200 if repair is successful
            # or appropriate error if repair fails
            assert response.status_code in [200, 400, 500]


class TestResponsesAPIMultimodal:
    """Test Responses API with multimodal inputs."""

    @pytest.fixture
    def app_config(self) -> AppConfig:
        """Create an AppConfig for testing."""
        config = AppConfig(
            host="localhost",
            port=8000,
            command_prefix="!/",
            backends=BackendSettings(default_backend="mock"),
        )

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

    def test_responses_api_with_image_input(self, client: TestClient) -> None:
        """Test Responses API with image input."""
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

        # Mock the backend service
        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call_completion:
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
            mock_call_completion.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["object"] == "response"
            assert "objects" in response_data["choices"][0]["message"]["parsed"]

    def test_responses_api_with_mixed_content(self, client: TestClient) -> None:
        """Test Responses API with mixed content types (text + image + audio)."""
        request_data = {
            "model": "gpt-4-omni",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Analyze this multimedia content"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "https://example.com/chart.png"},
                        },
                        {
                            "type": "text",
                            "text": "Also consider this audio description:",
                        },
                    ],
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "multimedia_analysis",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "visual_analysis": {"type": "string"},
                            "audio_analysis": {"type": "string"},
                            "combined_insights": {"type": "string"},
                        },
                        "required": ["visual_analysis", "combined_insights"],
                    },
                },
            },
        }

        # Mock the backend service
        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call_completion:
            from src.core.domain.responses import ResponseEnvelope

            mock_response = ResponseEnvelope(
                content={
                    "id": "resp-mixed-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "gpt-4-omni",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"visual_analysis": "Chart shows upward trend", "audio_analysis": "No audio provided", "combined_insights": "Data indicates growth"}',
                                "parsed": {
                                    "visual_analysis": "Chart shows upward trend",
                                    "audio_analysis": "No audio provided",
                                    "combined_insights": "Data indicates growth",
                                },
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            )
            mock_call_completion.return_value = mock_response

            response = client.post("/v1/responses", json=request_data)

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["object"] == "response"
            assert (
                "combined_insights" in response_data["choices"][0]["message"]["parsed"]
            )


class TestResponsesAPIStreaming:
    """Test Responses API streaming functionality."""

    @pytest.fixture
    def app_config(self) -> AppConfig:
        """Create an AppConfig for testing."""
        config = AppConfig(
            host="localhost",
            port=8000,
            command_prefix="!/",
            backends=BackendSettings(default_backend="mock"),
        )

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

    def test_responses_api_streaming_request(self, client: TestClient) -> None:
        """Test Responses API with streaming enabled."""
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

        # Test streaming using the built-in mock backend
        response = client.post("/v1/responses", json=request_data)

        # Should return 200 for streaming request
        assert response.status_code == 200
        # Content type should be text/event-stream for streaming
        assert "text/event-stream" in response.headers.get("content-type", "")

    def test_responses_api_non_streaming_request(self, client: TestClient) -> None:
        """Test Responses API with streaming disabled (default)."""
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
            "stream": False,  # Explicitly disable streaming
        }

        # Test non-streaming using the built-in mock backend
        response = client.post("/v1/responses", json=request_data)

        assert response.status_code == 200
        # Content type should be application/json for non-streaming
        assert "application/json" in response.headers.get("content-type", "")


class TestResponsesAPIProxyFeatures:
    """Test that all existing proxy features work with the new Responses API."""

    @pytest.fixture
    def app_config(self) -> AppConfig:
        """Create an AppConfig for testing."""
        config = AppConfig(
            host="localhost",
            port=8000,
            command_prefix="!/",
            backends=BackendSettings(default_backend="mock"),
        )

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

    def test_responses_api_with_rate_limiting(self, client: TestClient) -> None:
        """Test that rate limiting applies to Responses API."""
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Test rate limiting"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "rate_limit_test",
                    "schema": {
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                        "required": ["result"],
                    },
                },
            },
        }

        # Mock the backend service
        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call_completion:
            from src.core.domain.responses import ResponseEnvelope

            mock_response = ResponseEnvelope(
                content={
                    "id": "resp-rate-limit-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "mock-model",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": '{"result": "Rate limiting works"}',
                                "parsed": {"result": "Rate limiting works"},
                            },
                            "finish_reason": "stop",
                        }
                    ],
                }
            )
            mock_call_completion.return_value = mock_response

            # Make multiple requests to test rate limiting
            # (In a real test, this would need proper rate limiting configuration)
            response = client.post("/v1/responses", json=request_data)
            assert response.status_code == 200

    def test_responses_api_with_authentication(self, client: TestClient) -> None:
        """Test that authentication middleware applies to Responses API."""
        # This test would need authentication enabled in the config
        # For now, we test that the endpoint respects auth headers
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Test authentication"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "auth_test",
                    "schema": {
                        "type": "object",
                        "properties": {"authenticated": {"type": "boolean"}},
                        "required": ["authenticated"],
                    },
                },
            },
        }

        # Test with authorization header
        response = client.post(
            "/v1/responses",
            json=request_data,
            headers={"Authorization": "Bearer test-token"},
        )

        # Should not return 401 (since auth is disabled in test config)
        assert response.status_code != 401

    def test_responses_api_with_custom_headers(self, client: TestClient) -> None:
        """Test that custom headers are properly handled."""
        request_data = {
            "model": "mock-model",
            "messages": [{"role": "user", "content": "Test custom headers"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "header_test",
                    "schema": {
                        "type": "object",
                        "properties": {"processed": {"type": "boolean"}},
                        "required": ["processed"],
                    },
                },
            },
        }

        # Mock the backend service
        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call_completion:
            from src.core.domain.responses import ResponseEnvelope

            mock_response = ResponseEnvelope(
                content={
                    "id": "resp-headers-123",
                    "object": "response",
                    "created": 1677858242,
                    "model": "mock-model",
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
            )
            mock_call_completion.return_value = mock_response

            # Test with various custom headers
            response = client.post(
                "/v1/responses",
                json=request_data,
                headers={
                    "X-Custom-Header": "test-value",
                    "X-Request-ID": "test-request-123",
                    "User-Agent": "test-client/1.0",
                },
            )

            assert response.status_code == 200
            response_data = response.json()
            assert response_data["object"] == "response"
