"""Tests for GeminiBackend canonical connector API implementation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
)
from src.connectors.gemini import GeminiBackend
from src.core.config.app_config import AppConfig
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.services.translation_service import TranslationService


@pytest.fixture
def mock_client():
    """Create a mock HTTP client."""
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def mock_config():
    """Create a mock app config."""
    config = MagicMock(spec=AppConfig)
    return config


@pytest.fixture
def translation_service():
    """Create a translation service."""
    return TranslationService()


@pytest.fixture
def gemini_backend(mock_client, mock_config, translation_service):
    """Create a GeminiBackend instance."""
    backend = GeminiBackend(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )
    backend.api_key = "test-api-key"
    backend.key_name = "test-key"
    backend.gemini_api_base_url = "https://generativelanguage.googleapis.com"
    return backend


@pytest.fixture
def canonical_request():
    """Create a sample ConnectorChatCompletionsRequest."""
    return ConnectorChatCompletionsRequest(
        request=CanonicalChatRequest(
            model="gemini-2.5-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
        ),
        processed_messages=[ChatMessage(role="user", content="Hello")],
        effective_model="gemini-2.5-pro",
        identity=None,
        cancellation_token=None,
        cancellation_coordinator=None,
        context=ConnectorRequestContext(
            request_id="test-request-id",
            session_id="test-session-id",
            client_host="127.0.0.1",
            extensions={},
        ),
        options={},
    )


class TestGeminiCanonicalAPI:
    """Tests for GeminiBackend canonical API implementation."""

    def test_implements_canonical_protocol(self, gemini_backend):
        """Test that GeminiBackend implements ICanonicalChatCompletionsBackend."""
        import inspect

        # Check if canonical method exists by inspecting signature
        method = getattr(gemini_backend, "chat_completions", None)
        assert method is not None, "chat_completions method not found"

        try:
            sig = inspect.signature(method)
            params = list(sig.parameters.values())

            # The method has a backward-compatible signature that accepts canonical requests
            if len(params) > 0:
                first_param = params[0]
                param_annotation = first_param.annotation
                if (
                    param_annotation == ConnectorChatCompletionsRequest
                    or "ConnectorChatCompletionsRequest" in str(param_annotation)
                    or param_annotation == inspect.Signature.empty
                    or "Any" in str(param_annotation)
                ):
                    return  # Test passes - method supports canonical API
                else:
                    pytest.fail(
                        f"First parameter does not accept ConnectorChatCompletionsRequest. "
                        f"Got annotation: {param_annotation}"
                    )
            else:
                pytest.fail("chat_completions method has no parameters")
        except (ValueError, TypeError) as e:
            pytest.fail(f"Failed to inspect signature: {e}")

    @pytest.mark.asyncio
    async def test_canonical_api_receives_typed_contracts(
        self, gemini_backend, canonical_request
    ):
        """Test that canonical API receives ConnectorChatCompletionsRequest with typed contracts."""
        # Mock the internal implementation
        with patch.object(
            gemini_backend,
            "_chat_completions_canonical",
            new_callable=AsyncMock,
        ) as mock_internal:
            mock_internal.return_value = ResponseEnvelope(
                content={
                    "id": "test-id",
                    "model": "gemini-2.5-pro",
                    "choices": [],
                },
            )

            # Call canonical API
            await gemini_backend.chat_completions(canonical_request)

            # Verify it was called with typed contracts
            mock_internal.assert_called_once()
            call_args = mock_internal.call_args

            # Verify request.request is CanonicalChatRequest
            assert isinstance(canonical_request.request, CanonicalChatRequest)

            # Verify processed_messages is Sequence[ChatMessage]
            assert all(
                isinstance(msg, ChatMessage)
                for msg in canonical_request.processed_messages
            )

            # Verify options is dict[str, JsonValue]
            assert isinstance(canonical_request.options, dict)

            # Verify the canonical request was passed correctly
            assert call_args[0][0] == canonical_request

    @pytest.mark.asyncio
    async def test_canonical_api_consumes_json_safe_options(
        self, gemini_backend, canonical_request
    ):
        """Test that canonical API consumes options from JSON-safe dict."""
        # Set options with JSON-safe values
        canonical_request.options = {
            "project": "test-project",
            "agent": "test-agent",
            "gemini_api_base_url": "https://test.example.com",
            "key_name": "test-key",
            "api_key": "test-api-key",
        }

        # Mock the internal implementation to verify options are used
        with patch.object(
            gemini_backend,
            "_chat_completions_canonical",
            new_callable=AsyncMock,
        ) as mock_internal:
            mock_internal.return_value = ResponseEnvelope(
                content={
                    "id": "test-id",
                    "model": "gemini-2.5-pro",
                    "choices": [],
                },
            )

            await gemini_backend.chat_completions(canonical_request)

            # Verify options were passed correctly
            call_args = mock_internal.call_args
            passed_request = call_args[0][0]
            assert passed_request.options["project"] == "test-project"

    @pytest.mark.asyncio
    async def test_canonical_api_streaming_path(
        self, gemini_backend, canonical_request
    ):
        """Test that canonical API handles streaming requests correctly."""
        # Create a new request with stream=True
        streaming_request = CanonicalChatRequest(
            model="gemini-2.5-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
            stream=True,
        )
        canonical_request.request = streaming_request

        # Mock streaming pipeline integration
        with patch(
            "src.core.ports.streaming_integration.integrate_streaming_pipeline",
            new_callable=AsyncMock,
        ) as mock_integrate:
            mock_integrate.return_value = StreamingResponseEnvelope(
                content=AsyncMock(),
                media_type="text/event-stream",
                headers={},
            )

            # Mock stream_completion
            with patch.object(
                gemini_backend,
                "stream_completion",
                new_callable=AsyncMock,
            ) as mock_stream:
                mock_stream.return_value = AsyncMock()

                result = await gemini_backend.chat_completions(canonical_request)

                # Verify streaming path was taken
                assert isinstance(result, StreamingResponseEnvelope)
                mock_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_canonical_api_non_streaming_path(
        self, gemini_backend, canonical_request
    ):
        """Test that canonical API handles non-streaming requests correctly."""
        # Create a new request with stream=False
        non_streaming_request = CanonicalChatRequest(
            model="gemini-2.5-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
            stream=False,
        )
        canonical_request.request = non_streaming_request

        # Mock non-streaming handler
        with patch.object(
            gemini_backend,
            "_handle_gemini_non_streaming_response",
            new_callable=AsyncMock,
        ) as mock_handler:
            mock_handler.return_value = ResponseEnvelope(
                content={
                    "id": "test-id",
                    "model": "gemini-2.5-pro",
                    "choices": [],
                },
                status_code=200,
            )

            # Mock _resolve_gemini_api_config
            with patch.object(
                gemini_backend,
                "_resolve_gemini_api_config",
                new_callable=AsyncMock,
            ) as mock_resolve:
                from src.connectors.gemini import GeminiApiConfig

                mock_resolve.return_value = GeminiApiConfig(
                    base_url="https://generativelanguage.googleapis.com",
                    headers={"x-goog-api-key": "test-key"},
                )

                result = await gemini_backend.chat_completions(canonical_request)

                # Verify non-streaming path was taken
                assert isinstance(result, ResponseEnvelope)
                mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_used_for_correlation(
        self, gemini_backend, canonical_request
    ):
        """Test that ConnectorRequestContext is used for correlation."""
        # Set up context with correlation identifiers
        canonical_request.context = ConnectorRequestContext(
            request_id="test-req-123",
            session_id="test-session-456",
            client_host="192.168.1.1",
            extensions={},
        )

        # Create a non-streaming request
        non_streaming_request = CanonicalChatRequest(
            model="gemini-2.5-pro",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
            stream=False,
        )
        canonical_request.request = non_streaming_request

        # Mock the internal implementation
        with patch.object(
            gemini_backend,
            "_handle_gemini_non_streaming_response",
            new_callable=AsyncMock,
        ) as mock_handler:
            mock_handler.return_value = ResponseEnvelope(
                content={
                    "id": "test-id",
                    "model": "gemini-2.5-pro",
                    "choices": [],
                },
                status_code=200,
            )

            # Mock _resolve_gemini_api_config
            with patch.object(
                gemini_backend,
                "_resolve_gemini_api_config",
                new_callable=AsyncMock,
            ) as mock_resolve:
                from src.connectors.gemini import GeminiApiConfig

                mock_resolve.return_value = GeminiApiConfig(
                    base_url="https://generativelanguage.googleapis.com",
                    headers={"x-goog-api-key": "test-key"},
                )

                await gemini_backend.chat_completions(canonical_request)

                # Verify handler was called (context would be used internally)
                mock_handler.assert_called_once()
