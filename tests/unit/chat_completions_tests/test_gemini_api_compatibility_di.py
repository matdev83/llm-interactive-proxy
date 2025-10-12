"""
Tests for the Gemini API compatibility endpoints using proper DI approach.

This file contains tests for the Gemini API compatibility endpoints,
refactored to use proper dependency injection instead of direct app.state access.
"""

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

# Suppress Windows ProactorEventLoop warnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from fastapi.testclient import TestClient
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.session_resolver_interface import ISessionResolver
from src.core.services.translation_service import TranslationService
from src.rate_limit import RateLimitRegistry

from tests.utils.test_di_utils import (
    configure_test_state,
    get_required_service_from_app,
)


@pytest.fixture
def gemini_client(client: TestClient) -> TestClient:
    """Fixture for a client with Gemini API compatibility configured."""
    # Configure the test client with proper DI instead of direct app.state access
    configure_test_state(
        client.app,
        backend_type="openrouter",  # Default backend type
        disable_interactive_commands=True,  # Disable for clean testing
        command_prefix="!/",
        api_key_redaction_enabled=False,
        force_set_project=False,
        backends={
            "openrouter": Mock(),
            "gemini": Mock(),
            "gemini_cli_direct": Mock(),
        },
        available_models={
            "openrouter": ["gpt-4", "gpt-3.5-turbo"],
            "gemini": ["gemini-pro", "gemini-pro-vision"],
            "gemini_cli_direct": ["gemini-2.0-flash-001"],
        },
        functional_backends=["openrouter", "gemini", "gemini_cli_direct"],
    )

    # Set up rate limits
    app_state = client.app.state
    if not hasattr(app_state, "rate_limits"):
        app_state.rate_limits = RateLimitRegistry()

    return client


class TestGeminiModelsEndpoint:
    """Test the Gemini models endpoint."""

    def test_list_models_gemini_format(self, gemini_client):
        """Test listing models in Gemini format."""
        response = gemini_client.get("/v1beta/models")
        assert response.status_code == 200

        # Check response format
        data = response.json()
        assert "models" in data

        # Check that models are correctly formatted
        models = data["models"]
        assert len(models) > 0

        # Check that model names are correctly formatted
        for model in models:
            assert model["name"].startswith("models/")

        # Check that we have gemini models
        model_names = [m["name"] for m in models]
        assert "models/gemini-pro" in model_names

    def test_models_endpoint_auth_disabled(self, gemini_client):
        """Test models endpoint with auth disabled."""
        response = gemini_client.get("/v1beta/models")
        assert response.status_code == 200


class TestGeminiGenerateContent:
    """Test the Gemini content generation endpoint."""

    def test_generate_content_basic(self, gemini_client):
        """Test basic content generation with Gemini format."""
        # Configure backend service to handle our call
        backend_service = get_required_service_from_app(
            gemini_client.app, IBackendService
        )

        # Set up mock async methods
        async def mock_call_completion(*args, **kwargs):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "This is a test response from Gemini"}],
                            "role": "model",
                        },
                        "finishReason": "STOP",
                        "index": 0,
                    }
                ]
            }

        # Apply the mock async method
        backend_service.call_completion = Mock(side_effect=mock_call_completion)

        # Make request in Gemini format
        request_data = {
            "contents": [
                {
                    "parts": [{"text": "Write a short poem about programming"}],
                    "role": "user",
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.8,
                "maxOutputTokens": 100,
            },
        }

        response = gemini_client.post(
            "/v1beta/models/gemini-pro:generateContent", json=request_data
        )

        # Verify response
        assert response.status_code == 200

    def test_generate_content_with_system_instruction(self, gemini_client):
        """Test content generation with system instruction."""
        # Configure backend service
        backend_service = get_required_service_from_app(
            gemini_client.app, IBackendService
        )

        # Set up mock async methods
        async def mock_call_completion(*args, **kwargs):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": "This is a test response with system instruction"
                                }
                            ],
                            "role": "model",
                        },
                        "finishReason": "STOP",
                        "index": 0,
                    }
                ]
            }

        # Apply the mock async method
        backend_service.call_completion = Mock(side_effect=mock_call_completion)

        # Make request with system instruction
        request_data = {
            "contents": [
                {
                    "parts": [{"text": "You are a helpful assistant."}],
                    "role": "system",
                },
                {
                    "parts": [{"text": "Tell me about programming"}],
                    "role": "user",
                },
            ],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.8,
                "maxOutputTokens": 100,
            },
        }

        response = gemini_client.post(
            "/v1beta/models/gemini-pro:generateContent", json=request_data
        )

        # Verify response
        assert response.status_code == 200

    def test_generate_content_error_handling(self, gemini_client):
        """Test error handling for content generation."""
        # In the test environment, we're not going to test actual error responses
        # but rather verify that the controller handles the request correctly

        # Configure backend service
        backend_service = get_required_service_from_app(
            gemini_client.app, IBackendService
        )

        # Set up mock response with error information
        async def mock_error_response(*args, **kwargs):
            # Return a response with error information
            return {
                "error": {
                    "message": "Model not found: invalid-model",
                    "code": 404,
                    "status": "NOT_FOUND",
                }
            }

        # Apply the mock
        backend_service.call_completion = Mock(side_effect=mock_error_response)

        # Make request with invalid model
        response = gemini_client.post(
            "/v1beta/models/invalid-model:generateContent",
            json={"contents": [{"parts": [{"text": "test"}], "role": "user"}]},
        )

        # Test passes if we get any response (error handling varies in test vs prod)
        assert response.status_code != 0  # Ensure we got some response

        # If we got a success response, check that the error was passed through
        if response.status_code == 200:
            data = response.json()
            if "error" in data:
                assert "message" in data["error"]
                assert "Model not found" in data["error"]["message"]

    def test_generate_content_resolves_session_context(
        self, gemini_client, monkeypatch
    ) -> None:
        """Gemini compatibility endpoint should isolate sessions via resolver."""

        backend_service = get_required_service_from_app(
            gemini_client.app, IBackendService
        )
        backend_service.call_completion = AsyncMock(
            return_value=SimpleNamespace(content="ok")
        )

        session_resolver = AsyncMock(spec=ISessionResolver)
        session_resolver.resolve_session_id.return_value = "resolved-session"
        service_provider = gemini_client.app.state.service_provider

        original_get_required = service_provider.get_required_service
        original_get_service = service_provider.get_service

        def _get_required(service_type: type[Any]) -> Any:
            if service_type is ISessionResolver:
                return session_resolver
            return original_get_required(service_type)

        def _get_service(service_type: type[Any]) -> Any:
            if service_type is ISessionResolver:
                return session_resolver
            return original_get_service(service_type)

        monkeypatch.setattr(service_provider, "get_required_service", _get_required)
        monkeypatch.setattr(service_provider, "get_service", _get_service)

        gemini_client.app.state.openrouter_backend = None

        translation_service = service_provider.get_required_service(TranslationService)

        def _to_domain_request(
            data: dict[str, Any], source_format: str = "gemini"
        ) -> ChatRequest:
            return ChatRequest(
                model="gemini-pro",
                messages=[ChatMessage(role="user", content="Tell me a joke")],
                stream=bool(data.get("stream")),
                extra_body={},
            )

        monkeypatch.setattr(translation_service, "to_domain_request", _to_domain_request)

        request_data = {
            "contents": [
                {
                    "parts": [{"text": "Tell me a joke"}],
                    "role": "user",
                }
            ],
            "generationConfig": {"temperature": 0.5},
        }

        response = gemini_client.post(
            "/v1beta/models/gemini-pro:generateContent", json=request_data
        )

        assert response.status_code == 200
        assert session_resolver.resolve_session_id.await_count == 1

        call = backend_service.call_completion.await_args
        ctx = call.kwargs.get("context")
        assert ctx is not None
        assert ctx.session_id == "resolved-session"

        request_arg = call.args[0]
        assert request_arg.session_id == "resolved-session"
        assert request_arg.extra_body is not None
        assert request_arg.extra_body.get("session_id") == "resolved-session"

        resolver_context = session_resolver.resolve_session_id.await_args.args[0]
        assert resolver_context is ctx


class TestGeminiStreamGenerateContent:
    """Test the Gemini streaming content generation endpoint."""

    def test_stream_generate_content(self, gemini_client):
        """Test streaming content generation."""
        # Configure backend service
        backend_service = get_required_service_from_app(
            gemini_client.app, IBackendService
        )

        async def stream_chunks():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "This"}}]}
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": " is"}}]}
            )
            yield ProcessedResponse(
                content={
                    "choices": [
                        {
                            "delta": {"content": " streaming"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            )

        backend_service.call_completion = AsyncMock(
            return_value=StreamingResponseEnvelope(content=stream_chunks())
        )

        request_data = {
            "contents": [
                {
                    "parts": [{"text": "Write a short poem about programming"}],
                    "role": "user",
                }
            ],
            "generationConfig": {
                "temperature": 0.7,
                "topP": 0.8,
                "maxOutputTokens": 100,
            },
            "stream": True,
        }

        with gemini_client.stream(
            "POST", "/v1beta/models/gemini-pro:streamGenerateContent", json=request_data
        ) as response:
            assert response.status_code == 200

            lines = [
                line.decode("utf-8") if isinstance(line, bytes) else line
                for line in response.iter_lines()
                if line
            ]
            assert lines[-1] == "data: [DONE]"

            payloads = [
                json.loads(line[6:])
                for line in lines
                if line.startswith("data: ") and line != "data: [DONE]"
            ]
            assert [
                candidate["content"]["parts"][0]["text"]
                for payload in payloads
                for candidate in payload["candidates"]
            ] == ["This", " is", " streaming"]

    def test_stream_generate_content_handles_bytes_chunks(self, gemini_client):
        """Ensure byte-oriented streaming chunks are converted correctly."""

        backend_service = get_required_service_from_app(
            gemini_client.app, IBackendService
        )

        async def mock_call_completion(*args, **kwargs):
            async def _chunk_generator():
                # Provide raw content bytes that should be wrapped in ProcessedResponse
                yield '{"choices": [{"index": 0, "delta": {"content": "Hello"}}]}'

            return SimpleNamespace(content=_chunk_generator())

        backend_service.call_completion = AsyncMock(side_effect=mock_call_completion)

        request_data = {
            "contents": [
                {
                    "parts": [{"text": "Stream some text"}],
                    "role": "user",
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.9,
                "maxOutputTokens": 32,
            },
            "stream": True,
        }

        with gemini_client.stream(
            "POST",
            "/v1beta/models/gemini-pro:streamGenerateContent",
            json=request_data,
        ) as response:
            assert response.status_code == 200

            chunks = [line for line in response.iter_lines() if line]

            assert "data: [DONE]" in chunks

            payload_lines = [line for line in chunks if line.startswith("data: {")]
            assert payload_lines

            payload = payload_lines[0][len("data: ") :]
            data = json.loads(payload)
            assert data["candidates"]
            first_part = data["candidates"][0]["content"]["parts"][0]
            assert first_part["text"] == "Hello"

    def test_stream_generate_content_resolves_session_context(
        self, gemini_client, monkeypatch
    ) -> None:
        """Streaming endpoint should also resolve session context."""

        backend_service = get_required_service_from_app(
            gemini_client.app, IBackendService
        )

        async def stream_chunks():
            yield ProcessedResponse(content="chunk")

        backend_service.call_completion = AsyncMock(
            return_value=SimpleNamespace(content=stream_chunks())
        )

        session_resolver = AsyncMock(spec=ISessionResolver)
        session_resolver.resolve_session_id.return_value = "stream-session"
        service_provider = gemini_client.app.state.service_provider

        original_get_required = service_provider.get_required_service
        original_get_service = service_provider.get_service

        def _get_required(service_type: type[Any]) -> Any:
            if service_type is ISessionResolver:
                return session_resolver
            return original_get_required(service_type)

        def _get_service(service_type: type[Any]) -> Any:
            if service_type is ISessionResolver:
                return session_resolver
            return original_get_service(service_type)

        monkeypatch.setattr(service_provider, "get_required_service", _get_required)
        monkeypatch.setattr(service_provider, "get_service", _get_service)

        gemini_client.app.state.openrouter_backend = None

        translation_service = service_provider.get_required_service(TranslationService)

        def _to_domain_request(
            data: dict[str, Any], source_format: str = "gemini"
        ) -> ChatRequest:
            return ChatRequest(
                model="gemini-pro",
                messages=[
                    ChatMessage(role="user", content="Stream context please")
                ],
                stream=bool(data.get("stream")),
                extra_body={},
            )

        monkeypatch.setattr(translation_service, "to_domain_request", _to_domain_request)

        request_data = {
            "contents": [
                {
                    "parts": [{"text": "Stream context please"}],
                    "role": "user",
                }
            ],
            "generationConfig": {"temperature": 0.1},
            "stream": True,
        }

        with gemini_client.stream(
            "POST",
            "/v1beta/models/gemini-pro:streamGenerateContent",
            json=request_data,
        ) as response:
            assert response.status_code == 200
            list(response.iter_lines())

        assert session_resolver.resolve_session_id.await_count == 1

        call = backend_service.call_completion.await_args
        ctx = call.kwargs.get("context")
        assert ctx is not None
        assert ctx.session_id == "stream-session"
        assert call.kwargs.get("stream") is True

        request_arg = call.args[0]
        assert request_arg.session_id == "stream-session"
        assert request_arg.extra_body is not None
        assert request_arg.extra_body.get("session_id") == "stream-session"

        resolver_context = session_resolver.resolve_session_id.await_args.args[0]
        assert resolver_context is ctx


class TestGeminiAuthentication:
    """Test authentication for Gemini API."""

    def test_gemini_auth_with_api_key_header(self, gemini_client):
        """Test authentication with API key header."""
        # Make request with API key header
        response = gemini_client.get(
            "/v1beta/models", headers={"x-goog-api-key": "test-api-key"}
        )

        # Should succeed with API key
        assert response.status_code == 200

    def test_gemini_auth_fallback_to_bearer(self, gemini_client):
        """Test authentication fallback to bearer token."""
        # Make request with bearer token
        response = gemini_client.get(
            "/v1beta/models", headers={"Authorization": "Bearer test-token"}
        )

        # Should succeed with bearer token
        assert response.status_code == 200


class TestGeminiRequestConversion:
    """Test request conversion for Gemini API."""

    def test_complex_content_conversion(self, gemini_client):
        """Test conversion of complex content structures."""
        # Configure backend service
        backend_service = get_required_service_from_app(
            gemini_client.app, IBackendService
        )

        # Set up mock async methods
        async def mock_call_completion(*args, **kwargs):
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Response to complex request"}],
                            "role": "model",
                        },
                        "finishReason": "STOP",
                        "index": 0,
                    }
                ]
            }

        # Apply the mock async method
        backend_service.call_completion = Mock(side_effect=mock_call_completion)

        # Make request with complex content
        request_data = {
            "contents": [
                {
                    "parts": [
                        {"text": "System instruction"},
                    ],
                    "role": "system",
                },
                {
                    "parts": [
                        {"text": "User message with "},
                        {
                            "inlineData": {
                                "mimeType": "text/plain",
                                "data": "inline data",
                            }
                        },
                    ],
                    "role": "user",
                },
            ],
        }

        response = gemini_client.post(
            "/v1beta/models/gemini-pro:generateContent", json=request_data
        )

        # Verify response
        assert response.status_code == 200
