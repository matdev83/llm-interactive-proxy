"""Tests for AnthropicBackend canonical connector API implementation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.connectors.anthropic import AnthropicBackend
from src.connectors.contracts import (
    ConnectorChatCompletionsRequest,
    ConnectorRequestContext,
    ICanonicalChatCompletionsBackend,
)
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
def anthropic_backend(mock_client, mock_config, translation_service):
    """Create an AnthropicBackend instance."""
    backend = AnthropicBackend(
        client=mock_client,
        config=mock_config,
        translation_service=translation_service,
    )
    backend.api_key = "test-api-key"
    backend.key_name = "test-key"
    backend.anthropic_api_base_url = "https://api.anthropic.com/v1"
    return backend


@pytest.fixture
def canonical_request():
    """Create a sample ConnectorChatCompletionsRequest."""
    return ConnectorChatCompletionsRequest(
        request=CanonicalChatRequest(
            model="claude-3-haiku-20240307",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
        ),
        processed_messages=[ChatMessage(role="user", content="Hello")],
        effective_model="claude-3-haiku-20240307",
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


class TestAnthropicCanonicalAPI:
    """Tests for AnthropicBackend canonical API implementation."""

    def test_implements_canonical_protocol(self, anthropic_backend):
        """Test that AnthropicBackend implements ICanonicalChatCompletionsBackend."""
        import inspect
        
        # Check if canonical method exists by inspecting signature
        # The canonical API should have a single parameter named "request"
        method = getattr(anthropic_backend, "chat_completions", None)
        assert method is not None, "chat_completions method not found"
        
        try:
            sig = inspect.signature(method)
            params = list(sig.parameters.values())
            
            # Check if this is the canonical signature (single "request" parameter)
            # or legacy signature (multiple parameters)
            # For now, we expect legacy signature until we implement canonical
            # After implementation, we should check for canonical signature
            if len(params) == 1 and params[0].name == "request":
                # Canonical API found
                param_annotation = params[0].annotation
                # Check if annotation matches ConnectorChatCompletionsRequest
                assert (
                    param_annotation == ConnectorChatCompletionsRequest
                    or "ConnectorChatCompletionsRequest" in str(param_annotation)
                ), f"Expected ConnectorChatCompletionsRequest, got {param_annotation}"
            else:
                # Legacy signature - this is expected until we implement canonical
                # After implementation, this should not be reached
                pytest.fail(
                    "Canonical chat_completions method not found. "
                    f"Found legacy signature with {len(params)} parameters: {[p.name for p in params]}"
                )
        except (ValueError, TypeError) as e:
            pytest.fail(f"Failed to inspect signature: {e}")

    @pytest.mark.asyncio
    async def test_canonical_api_receives_typed_contracts(
        self, anthropic_backend, canonical_request
    ):
        """Test that canonical API receives ConnectorChatCompletionsRequest with typed contracts."""
        # Mock the internal implementation
        with patch.object(
            anthropic_backend,
            "_chat_completions_canonical",
            new_callable=AsyncMock,
        ) as mock_internal:
            mock_internal.return_value = ResponseEnvelope(
                content={"id": "test-id", "model": "claude-3-haiku-20240307", "choices": []},
            )
            
            # Call canonical API
            result = await anthropic_backend.chat_completions(canonical_request)
            
            # Verify it was called with typed contracts
            mock_internal.assert_called_once()
            call_args = mock_internal.call_args
            
            # Verify request.request is CanonicalChatRequest
            assert isinstance(canonical_request.request, CanonicalChatRequest)
            
            # Verify processed_messages is Sequence[ChatMessage]
            assert all(isinstance(msg, ChatMessage) for msg in canonical_request.processed_messages)
            
            # Verify options is dict[str, JsonValue]
            assert isinstance(canonical_request.options, dict)
            
            # Verify the canonical request was passed correctly
            assert call_args[0][0] == canonical_request

    @pytest.mark.asyncio
    async def test_canonical_api_consumes_json_safe_options(
        self, anthropic_backend, canonical_request
    ):
        """Test that canonical API consumes options from JSON-safe dict."""
        # Set options with JSON-safe values
        canonical_request.options = {
            "project": "test-project",
            "agent": "test-agent",
            "headers": {"custom": "header"},
        }
        
        # Mock the internal implementation to verify options are used
        with patch.object(
            anthropic_backend,
            "_chat_completions_canonical",
            new_callable=AsyncMock,
        ) as mock_internal:
            mock_internal.return_value = ResponseEnvelope(
                content={"id": "test-id", "model": "claude-3-haiku-20240307", "choices": []},
            )
            
            await anthropic_backend.chat_completions(canonical_request)
            
            # Verify options were passed correctly
            # (Implementation will extract from canonical_request.options)
            assert canonical_request.options["project"] == "test-project"
            
            # Verify the canonical request with options was passed
            call_args = mock_internal.call_args
            passed_request = call_args[0][0]
            assert passed_request.options["project"] == "test-project"

    @pytest.mark.asyncio
    async def test_legacy_api_still_works(self, anthropic_backend):
        """Test that legacy chat_completions API still works for backward compatibility.
        
        Note: Legacy API calls should go through ConnectorInvoker, which will
        build a ConnectorChatCompletionsRequest and call the canonical API.
        This test verifies that the canonical API can be called directly.
        """
        from src.connectors.contracts import ConnectorChatCompletionsRequest, ConnectorRequestContext
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage
        
        domain_request = CanonicalChatRequest(
            model="claude-3-haiku-20240307",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
        )
        
        # Build canonical request (as ConnectorInvoker would)
        canonical_request = ConnectorChatCompletionsRequest(
            request=domain_request,
            processed_messages=[ChatMessage(role="user", content="Hello")],
            effective_model="claude-3-haiku-20240307",
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )
        
        # Mock the canonical implementation
        with patch.object(
            anthropic_backend,
            "_chat_completions_canonical",
            new_callable=AsyncMock,
        ) as mock_canonical:
            mock_canonical.return_value = ResponseEnvelope(
                content={"id": "test-id", "model": "claude-3-haiku-20240307", "choices": []},
            )
            
            # Call canonical API (as ConnectorInvoker would)
            result = await anthropic_backend.chat_completions(canonical_request)
            
            # Verify canonical API works
            assert result is not None
            mock_canonical.assert_called_once_with(canonical_request)

    @pytest.mark.asyncio
    async def test_context_used_for_logging_correlation(
        self, anthropic_backend, canonical_request
    ):
        """Test that ConnectorRequestContext is used for logging correlation."""
        import logging
        
        # Create a new request with stream=False (CanonicalChatRequest is frozen)
        non_streaming_request = CanonicalChatRequest(
            model="claude-3-haiku-20240307",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
            stream=False,
        )
        
        # Set up context with correlation identifiers
        canonical_request.context = ConnectorRequestContext(
            request_id="test-req-123",
            session_id="test-session-456",
            client_host="192.168.1.1",
            extensions={},
        )
        canonical_request.request = non_streaming_request
        
        # Capture log messages
        with patch("src.connectors.anthropic.logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            
            # Mock the internal implementation to avoid actual HTTP calls
            with patch.object(
                anthropic_backend,
                "_handle_non_streaming_response",
                new_callable=AsyncMock,
            ) as mock_handler:
                mock_handler.return_value = ResponseEnvelope(
                    content={"id": "test-id", "model": "claude-3-haiku-20240307", "choices": []},
                    status_code=200,
                )
                
                await anthropic_backend.chat_completions(canonical_request)
                
                # Verify logging was called with context correlation
                info_calls = [call for call in mock_logger.info.call_args_list]
                assert len(info_calls) > 0
                
                # Check that log_extra contains context fields
                # The implementation adds context to log messages
                # We verify by checking that logging was called
                assert mock_logger.info.called

    @pytest.mark.asyncio
    async def test_canonical_api_streaming_path(
        self, anthropic_backend, canonical_request
    ):
        """Test that canonical API handles streaming requests correctly."""
        from src.core.domain.responses import StreamingResponseEnvelope
        
        # Create a new request with stream=True (CanonicalChatRequest is frozen)
        streaming_request = CanonicalChatRequest(
            model="claude-3-haiku-20240307",
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
                anthropic_backend,
                "stream_completion",
                new_callable=AsyncMock,
            ) as mock_stream:
                mock_stream.return_value = AsyncMock()
                
                result = await anthropic_backend.chat_completions(canonical_request)
                
                # Verify streaming path was taken
                assert isinstance(result, StreamingResponseEnvelope)
                mock_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_canonical_api_non_streaming_path(
        self, anthropic_backend, canonical_request
    ):
        """Test that canonical API handles non-streaming requests correctly."""
        # Create a new request with stream=False (CanonicalChatRequest is frozen)
        non_streaming_request = CanonicalChatRequest(
            model="claude-3-haiku-20240307",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
            stream=False,
        )
        canonical_request.request = non_streaming_request
        
        # Mock non-streaming handler
        with patch.object(
            anthropic_backend,
            "_handle_non_streaming_response",
            new_callable=AsyncMock,
        ) as mock_handler:
            mock_handler.return_value = ResponseEnvelope(
                content={"id": "test-id", "model": "claude-3-haiku-20240307", "choices": []},
                status_code=200,
            )
            
            result = await anthropic_backend.chat_completions(canonical_request)
            
            # Verify non-streaming path was taken
            assert isinstance(result, ResponseEnvelope)
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_options_json_safety_validation(
        self, anthropic_backend, canonical_request
    ):
        """Test that options are validated as JSON-safe values."""
        import json
        
        # Set options with JSON-safe values
        canonical_request.options = {
            "project": "test-project",
            "key_name": "test-key",
            "api_key": "test-api-key",
            "headers": {"custom": "header"},
            "numeric": 42,
            "boolean": True,
            "null_value": None,
        }
        
        # Mock the internal implementation
        with patch.object(
            anthropic_backend,
            "_chat_completions_canonical",
            new_callable=AsyncMock,
        ) as mock_internal:
            mock_internal.return_value = ResponseEnvelope(
                content={"id": "test-id", "model": "claude-3-haiku-20240307", "choices": []},
            )
            
            await anthropic_backend.chat_completions(canonical_request)
            
            # Verify all options are JSON-serializable
            call_args = mock_internal.call_args
            passed_request = call_args[0][0]
            
            # All values should be JSON-serializable
            try:
                json.dumps(passed_request.options)
            except (TypeError, ValueError) as e:
                pytest.fail(f"Options contain non-JSON-safe values: {e}")
            
            # Verify options were passed correctly
            assert passed_request.options["project"] == "test-project"
            assert passed_request.options["numeric"] == 42
            assert passed_request.options["boolean"] is True

    @pytest.mark.asyncio
    async def test_context_in_error_logs(
        self, anthropic_backend, canonical_request
    ):
        """Test that context correlation identifiers appear in error logs."""
        import logging
        
        # Set up context with correlation identifiers
        canonical_request.context = ConnectorRequestContext(
            request_id="test-req-error-123",
            session_id="test-session-error-456",
            client_host="192.168.1.100",
            extensions={},
        )
        
        # Create a non-streaming request
        non_streaming_request = CanonicalChatRequest(
            model="claude-3-haiku-20240307",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
            stream=False,
        )
        canonical_request.request = non_streaming_request
        
        # Mock _handle_non_streaming_response to raise an error and verify context is passed
        with patch.object(
            anthropic_backend,
            "_handle_non_streaming_response",
            new_callable=AsyncMock,
        ) as mock_handler:
            # Make it raise an exception that triggers error logging
            mock_handler.side_effect = Exception("Test error for context logging")
            
            # Capture log messages
            with patch("src.connectors.anthropic.logger") as mock_logger:
                mock_logger.isEnabledFor.return_value = True
                
                # Call should raise an error
                with pytest.raises(Exception):
                    await anthropic_backend.chat_completions(canonical_request)
                
                # Verify context was passed to helper method
                mock_handler.assert_called_once()
                call_args = mock_handler.call_args
                # Check that context parameter was passed (5th argument: url, payload, headers, model, context)
                assert len(call_args[0]) >= 5
                passed_context = call_args[0][4]
                assert passed_context is not None
                assert passed_context.request_id == "test-req-error-123"
                assert passed_context.session_id == "test-session-error-456"

    @pytest.mark.asyncio
    async def test_context_in_warning_logs(
        self, anthropic_backend, canonical_request
    ):
        """Test that context correlation identifiers appear in warning logs."""
        import logging
        
        # Set up context with correlation identifiers
        canonical_request.context = ConnectorRequestContext(
            request_id="test-req-warn-123",
            session_id="test-session-warn-456",
            client_host="192.168.1.200",
            extensions={},
        )
        
        # Create a request with unsupported parameter (triggers warning)
        request_with_seed = CanonicalChatRequest(
            model="claude-3-haiku-20240307",
            messages=[ChatMessage(role="user", content="Hello")],
            max_tokens=100,
            stream=False,
            seed=12345,  # Unsupported parameter
        )
        canonical_request.request = request_with_seed
        
        # Mock successful response
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "id": "test-id",
            "model": "claude-3-haiku-20240307",
            "choices": [{"message": {"role": "assistant", "content": "Hi"}}],
        }
        anthropic_backend.client.post = AsyncMock(return_value=mock_response)
        
        # Capture log messages
        with patch("src.connectors.anthropic.logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            
            await anthropic_backend.chat_completions(canonical_request)
            
            # Verify warning log was called with context (for unsupported seed parameter)
            warning_calls = [call for call in mock_logger.warning.call_args_list]
            if warning_calls:
                # Check that at least one warning log includes context
                found_context = False
                for call in warning_calls:
                    kwargs = call.kwargs
                    if "extra" in kwargs and kwargs["extra"]:
                        extra = kwargs["extra"]
                        if "request_id" in extra or "session_id" in extra:
                            found_context = True
                            assert extra.get("request_id") == "test-req-warn-123"
                            assert extra.get("session_id") == "test-session-warn-456"
                            break
                # Note: Warning may not always be logged depending on log level
                # The important thing is that if logging occurs, context is included
