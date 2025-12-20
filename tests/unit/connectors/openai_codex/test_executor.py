"""Unit tests for ResponseExecutor service.

Tests cover error mapping, usage metadata, capture data handling, and streaming retry behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.contracts import (
    CodexPayload,
    CodexRequestContext,
    ProcessedMessage,
)
from src.connectors.openai_codex.executor import ResponseExecutor
from src.connectors.openai_codex.interfaces import ICredentialManager, IResponseExecutor
from src.core.common.exceptions import AuthenticationError, ServiceUnavailableError
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestResponseExecutor:
    """Test ResponseExecutor service implementation."""

    @pytest.fixture
    def mock_base_connector(self):
        """Create a mock base OpenAI connector."""
        connector = MagicMock()
        connector.client = MagicMock()
        connector.translation_service = MagicMock()
        connector.get_headers = MagicMock(
            return_value={"Authorization": "Bearer token"}
        )
        connector._handle_streaming_response = AsyncMock()
        # Mock methods that might be called during header building
        connector._codex_user_agent = MagicMock(return_value="test-user-agent")
        connector._codex_account_id = MagicMock(return_value=None)
        return connector

    @pytest.fixture
    def mock_credential_manager(self):
        """Create a mock credential manager."""
        manager = MagicMock(spec=ICredentialManager)
        manager.refresh_access_token = AsyncMock(return_value=True)
        manager.get_access_token = MagicMock(return_value="test_token")
        return manager

    @pytest.fixture
    def executor(self, mock_base_connector, mock_credential_manager):
        """Create a ResponseExecutor instance for testing."""
        return ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            max_retries=2,
            retry_backoff_seconds=(0.1, 0.2),
        )

    @pytest.fixture
    def sample_context(self):
        """Create a sample CodexRequestContext."""
        request = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=False,
        )
        return CodexRequestContext(
            request=request,
            processed_messages=[
                ProcessedMessage(
                    role="user",
                    content="Test message",
                    tool_calls=None,
                )
            ],
            effective_model="gpt-5.1-codex",
            capabilities=CodexClientCapabilities(),
            session_id="test-session-123",
        )

    @pytest.fixture
    def non_streaming_payload(self):
        """Create a non-streaming payload."""
        return CodexPayload(
            model="gpt-5.1-codex",
            input=[],
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=False,
            include=[],
            prompt_cache_key="test-key",
        )

    @pytest.fixture
    def streaming_payload(self):
        """Create a streaming payload."""
        return CodexPayload(
            model="gpt-5.1-codex",
            input=[],
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=True,
            include=[],
            prompt_cache_key="test-key",
        )

    def test_executor_implements_interface(self, executor):
        """Verify executor implements IResponseExecutor interface."""
        assert isinstance(executor, IResponseExecutor)

    @pytest.mark.asyncio
    async def test_execute_non_streaming_success(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test successful non-streaming execution."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "model": "gpt-5.1-codex",
            "choices": [{"message": {"role": "assistant", "content": "Response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }
        mock_response.headers = {"x-request-id": "req-123"}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {"content": "Response"}
        domain_response.usage = {"prompt_tokens": 10, "completion_tokens": 20}
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert isinstance(result, ResponseEnvelope)
        assert result.status_code == 200
        assert result.usage == domain_response.usage
        assert result.metadata["backend"] == "openai-codex"
        assert result.metadata["model"] == sample_context.effective_model
        assert result.metadata["session_id"] == sample_context.session_id

    @pytest.mark.asyncio
    async def test_execute_non_streaming_usage_metadata(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test that usage metadata is extracted correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "choices": [],
            "usage": {"prompt_tokens": 100, "completion_tokens": 200},
        }
        mock_response.headers = {}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {}
        domain_response.usage = {"prompt_tokens": 100, "completion_tokens": 200}
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert result.usage == domain_response.usage

    @pytest.mark.asyncio
    async def test_execute_non_streaming_capture_metadata(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test that capture metadata is included in response envelope."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "chatcmpl-123", "choices": []}
        mock_response.headers = {"x-request-id": "req-456"}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {}
        domain_response.usage = None
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert result.headers == {"x-request-id": "req-456"}
        assert result.metadata["backend"] == "openai-codex"

    @pytest.mark.asyncio
    async def test_execute_non_streaming_http_error(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test error mapping for HTTP errors."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": {"message": "Bad request"}}
        mock_response.text = '{"error": {"message": "Bad request"}}'
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(HTTPException) as exc_info:
            await executor.execute(non_streaming_payload, sample_context)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_execute_non_streaming_network_error(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test error mapping for network errors."""
        mock_base_connector.client.post = AsyncMock(
            side_effect=httpx.RequestError("Network error")
        )

        with pytest.raises(ServiceUnavailableError) as exc_info:
            await executor.execute(non_streaming_payload, sample_context)

        assert "Could not connect to backend" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_execute_non_streaming_no_auth(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test error when no auth credentials found."""
        mock_base_connector.get_headers.return_value = {}

        with pytest.raises(AuthenticationError) as exc_info:
            await executor.execute(non_streaming_payload, sample_context)

        assert "No auth credentials found" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_execute_non_streaming_timeout_error(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test timeout errors map to ServiceUnavailableError."""
        import httpx

        mock_base_connector.client.post = AsyncMock(
            side_effect=httpx.TimeoutException("Request timed out", request=MagicMock())
        )

        with pytest.raises(ServiceUnavailableError) as exc_info:
            await executor.execute(non_streaming_payload, sample_context)

        assert "Could not connect to backend" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_execute_non_streaming_invalid_response_format(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test invalid response format handling."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("Invalid JSON")
        mock_response.text = "Invalid response"
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        # Should raise an error when response can't be parsed
        with pytest.raises(ValueError):
            await executor.execute(non_streaming_payload, sample_context)

    @pytest.mark.asyncio
    async def test_execute_non_streaming_usage_missing(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test handling when usage metadata is missing from response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "choices": [{"message": {"content": "test"}}],
            # No usage field
        }
        mock_response.headers = {}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {}
        domain_response.usage = None  # No usage
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert result.usage is None

    @pytest.mark.asyncio
    async def test_execute_non_streaming_usage_unexpected_structure(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test handling when usage metadata has unexpected structure."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "choices": [],
        }
        mock_response.headers = {}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {}
        # Usage with unexpected structure
        domain_response.usage = {"unexpected": "structure"}
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        # Should preserve usage as-is (translation service handles structure)
        assert result.usage == {"unexpected": "structure"}

    @pytest.mark.asyncio
    async def test_execute_streaming_success(
        self, executor, mock_base_connector, sample_context, streaming_payload
    ):
        """Test successful streaming execution."""
        # Create chunks that will be yielded
        chunk1 = ProcessedResponse(
            content={"choices": [{"delta": {"content": "chunk1"}}]}
        )
        chunk2 = ProcessedResponse(
            content={"choices": [{"delta": {"content": "chunk2"}}]}
        )

        # Track if iterator is consumed
        iterator_consumed = []

        async def mock_iterator():
            iterator_consumed.append(True)
            yield chunk1
            yield chunk2

        # Create mock stream handle exactly like other streaming tests
        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {"x-request-id": "stream-123"}
        mock_stream_handle.cancel_callback = AsyncMock()
        # Set iterator attribute - MagicMock should handle this correctly
        mock_stream_handle.iterator = mock_iterator()

        mock_base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )

        # Verify the iterator is set correctly before execution
        assert hasattr(mock_stream_handle, "iterator"), "Iterator attribute must be set"
        assert mock_stream_handle.iterator is not None, "Iterator must not be None"

        result = await executor.execute(streaming_payload, sample_context)

        assert isinstance(result, StreamingResponseEnvelope)
        assert result.media_type == "text/event-stream"
        # Headers are set from headers_holder which is updated during iteration
        # Initially headers will be empty until stream is consumed
        assert isinstance(result.headers, dict)

        # Consume the stream to verify it works and headers are set
        # Note: The executor's _streaming_iterator() function:
        # 1. Gets stream_handle from _handle_streaming_response (line 254)
        # 2. Updates headers_holder from stream_handle.headers (line 307)
        # 3. Iterates over stream_handle.iterator and yields chunks (line 313)
        # The generator is lazy - it only executes when we iterate over result.content
        chunks = []

        # Verify _handle_streaming_response is called when we start consuming
        assert (
            not mock_base_connector._handle_streaming_response.called
        ), "Streaming handler should not be called until generator is consumed"

        # Start consuming the generator
        # The executor's _streaming_iterator() will:
        # - Call _handle_streaming_response to get stream_handle
        # - Update headers_holder from stream_handle.headers
        # - Iterate over stream_handle.iterator and yield chunks
        async for chunk in result.content:
            chunks.append(chunk)
            # Verify handler was called
            assert (
                mock_base_connector._handle_streaming_response.called
            ), "Streaming handler should be called when generator executes"
            # Headers should be populated after first chunk is processed
            # because headers_holder is updated before iteration starts (line 307)
            if len(chunks) == 1:
                assert result.headers == {"x-request-id": "stream-123"}

        # Verify iterator was consumed
        assert (
            iterator_consumed
        ), "Mock iterator was not consumed - generator may have exited early before iteration"
        assert (
            len(chunks) == 2
        ), f"Expected 2 chunks but got {len(chunks)}. Chunks: {chunks}"
        # Verify chunks are ProcessedResponse objects
        assert chunks[0] == chunk1
        assert chunks[1] == chunk2
        # After consuming all chunks, headers should still be set
        assert result.headers == {"x-request-id": "stream-123"}

    @pytest.mark.asyncio
    async def test_execute_streaming_handshake_auth_retry(
        self,
        executor,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ):
        """Test streaming handshake authentication retry."""

        async def empty_iterator():
            return
            yield  # Make it an async generator

        success_handle = MagicMock()
        success_handle.headers = {}
        success_handle.cancel_callback = AsyncMock()
        success_handle.iterator = empty_iterator()

        # First attempt fails with 401, second succeeds
        call_count = [0]

        async def handle_streaming_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise HTTPException(status_code=401, detail="Unauthorized")
            return success_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        result = await executor.execute(streaming_payload, sample_context)

        assert isinstance(result, StreamingResponseEnvelope)
        # Consume stream to trigger retry logic
        async for _ in result.content:
            pass
        # Should have attempted refresh once (on first 401)
        assert mock_credential_manager.refresh_access_token.call_count >= 1

    @pytest.mark.asyncio
    async def test_execute_streaming_handshake_auth_retry_exhausted(
        self,
        executor,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ):
        """Test streaming handshake auth retry exhaustion."""
        # Create executor with max_retries=0 to test exhaustion quickly
        executor_exhausted = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            max_retries=0,
            retry_backoff_seconds=(0.1,),
        )

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=HTTPException(status_code=401, detail="Unauthorized")
        )
        mock_credential_manager.refresh_access_token.return_value = True

        result = await executor_exhausted.execute(streaming_payload, sample_context)

        # Exception is raised when consuming the stream
        with pytest.raises(HTTPException) as exc_info:
            async for _ in result.content:
                pass

        assert exc_info.value.status_code == 401
        assert "openai_codex_stream_auth_failed" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_execute_streaming_chunk_auth_error_retry(
        self,
        executor,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ):
        """Test streaming chunk-level authentication error retry."""

        async def normal_iterator():
            yield ProcessedResponse(content={"choices": [{"delta": {"content": "ok"}}]})

        async def auth_error_iterator():
            yield ProcessedResponse(
                content={
                    "error": "auth_failed",
                    "details": {"status": 401},
                }
            )

        mock_stream_handle_auth_error = MagicMock()
        mock_stream_handle_auth_error.headers = {}
        mock_stream_handle_auth_error.cancel_callback = AsyncMock()
        mock_stream_handle_auth_error.iterator = auth_error_iterator()

        mock_stream_handle_success = MagicMock()
        mock_stream_handle_success.headers = {}
        mock_stream_handle_success.cancel_callback = AsyncMock()
        mock_stream_handle_success.iterator = normal_iterator()

        # First call returns handle with auth error, second call succeeds
        call_count = [0]

        async def handle_streaming_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_stream_handle_auth_error
            return mock_stream_handle_success

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        result = await executor.execute(streaming_payload, sample_context)

        assert isinstance(result, StreamingResponseEnvelope)
        # Consume stream to trigger retry logic
        chunks = []
        async for chunk in result.content:
            chunks.append(chunk)
        # Should have attempted refresh when auth error detected
        assert mock_credential_manager.refresh_access_token.call_count >= 1
        # Should eventually get successful chunks after retry
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_execute_streaming_chunk_auth_error_retry_exhausted(
        self,
        executor,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ):
        """Test streaming chunk-level auth retry exhaustion."""
        # Create executor with max_retries=0 to test exhaustion quickly
        executor_exhausted = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            max_retries=0,
            retry_backoff_seconds=(0.1,),
        )

        async def auth_error_iterator():
            yield ProcessedResponse(
                content={
                    "error": "auth_failed",
                    "details": {"status": 401},
                }
            )

        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = auth_error_iterator()
        mock_base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )
        mock_credential_manager.refresh_access_token.return_value = True

        result = await executor_exhausted.execute(streaming_payload, sample_context)

        # Should raise after retries exhausted
        with pytest.raises(HTTPException) as exc_info:
            async for _ in result.content:
                pass

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_execute_streaming_refresh_fails(
        self,
        executor,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ):
        """Test streaming when credential refresh fails."""
        # Create executor with max_retries=1 to test refresh failure
        executor_with_retries = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            max_retries=1,
            retry_backoff_seconds=(0.1,),
        )

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=HTTPException(status_code=401, detail="Unauthorized")
        )
        mock_credential_manager.refresh_access_token.return_value = False

        result = await executor_with_retries.execute(streaming_payload, sample_context)

        # Exception is raised when consuming the stream after refresh fails
        with pytest.raises(HTTPException) as exc_info:
            async for _ in result.content:
                pass

        assert exc_info.value.status_code == 401
        assert "openai_codex_stream_auth_failed" in str(exc_info.value.detail)

    def test_build_headers(self, executor, mock_base_connector, sample_context):
        """Test header building."""
        headers = executor._build_headers(sample_context.session_id)

        assert "Authorization" in headers
        assert headers["OpenAI-Beta"] == "responses=experimental"
        assert headers["Accept"] == "text/event-stream"
        assert headers["conversation_id"] == sample_context.session_id
        assert headers["session_id"] == sample_context.session_id

    def test_should_retry_for_auth_error_with_status(self, executor):
        """Test detection of auth error in chunk."""
        chunk = ProcessedResponse(
            content={
                "error": "auth_failed",
                "details": {"status": 401},
            }
        )

        assert executor._should_retry_for_auth_error(chunk) is True

    def test_should_retry_for_auth_error_with_nested_status(self, executor):
        """Test detection of auth error in nested metadata."""
        chunk = ProcessedResponse(
            content={
                "error": "auth_failed",
                "details": {
                    "metadata": {"status_code": 403},
                },
            }
        )

        assert executor._should_retry_for_auth_error(chunk) is True

    def test_should_retry_for_auth_error_no_error(self, executor):
        """Test that normal chunks don't trigger retry."""
        chunk = ProcessedResponse(
            content={"choices": [{"delta": {"content": "normal"}}]}
        )

        assert executor._should_retry_for_auth_error(chunk) is False

    def test_should_retry_for_auth_error_with_code_heuristic(self, executor):
        """Test detection of auth error using code-based heuristics."""
        # Test various auth-related codes
        auth_codes = [
            "auth",
            "unauthorized",
            "invalid_token",
            "invalid_api_key",
            "token_expired",
            "access_denied",
            "AUTH_ERROR",
            "UnauthorizedAccess",
        ]

        for code in auth_codes:
            chunk = ProcessedResponse(
                content={
                    "error": "some_error",
                    "details": {"code": code},
                }
            )
            assert (
                executor._should_retry_for_auth_error(chunk) is True
            ), f"Should detect auth error for code: {code}"

    def test_should_retry_for_auth_error_with_code_in_content(self, executor):
        """Test detection when code is in content root instead of details."""
        chunk = ProcessedResponse(
            content={
                "code": "invalid_token",
                "message": "Token is invalid",
            }
        )

        assert executor._should_retry_for_auth_error(chunk) is True

    def test_should_retry_for_auth_error_with_message_heuristic_401(self, executor):
        """Test detection using message-based heuristics for 401."""
        chunk = ProcessedResponse(
            content={
                "error": "Request failed with status 401",
                "message": "Unauthorized access",
            }
        )

        assert executor._should_retry_for_auth_error(chunk) is True

    def test_should_retry_for_auth_error_with_message_heuristic_403(self, executor):
        """Test detection using message-based heuristics for 403."""
        chunk = ProcessedResponse(
            content={
                "error": "Request failed with status 403",
                "message": "Forbidden",
            }
        )

        assert executor._should_retry_for_auth_error(chunk) is True

    def test_should_retry_for_auth_error_with_message_heuristic_unauthorized(
        self, executor
    ):
        """Test detection using message-based heuristics for 'unauthorized' keyword."""
        chunk = ProcessedResponse(
            content={
                "error": "Unauthorized request",
                "message": "Access denied",
            }
        )

        assert executor._should_retry_for_auth_error(chunk) is True

    def test_should_retry_for_auth_error_with_message_heuristic_token_expired(
        self, executor
    ):
        """Test detection using message-based heuristics for 'token expired'."""
        chunk = ProcessedResponse(
            content={
                "error": "Token has expired",
                "message": "Please refresh your token",
            }
        )

        assert executor._should_retry_for_auth_error(chunk) is True

    def test_should_retry_for_auth_error_with_message_heuristic_in_error_flag(
        self, executor
    ):
        """Test detection when auth keywords are in error flag."""
        chunk = ProcessedResponse(
            content={
                "error": "401 Unauthorized",
                "details": {},
            }
        )

        assert executor._should_retry_for_auth_error(chunk) is True

    def test_should_retry_for_auth_error_with_message_heuristic_in_message(
        self, executor
    ):
        """Test detection when auth keywords are in message field."""
        chunk = ProcessedResponse(
            content={
                "message": "403 Forbidden - Invalid credentials",
                "details": {},
            }
        )

        assert executor._should_retry_for_auth_error(chunk) is True

    def test_should_retry_for_auth_error_non_auth_code(self, executor):
        """Test that non-auth codes don't trigger retry."""
        non_auth_codes = [
            "rate_limit",
            "invalid_request",
            "model_not_found",
            "server_error",
            "timeout",
        ]

        for code in non_auth_codes:
            chunk = ProcessedResponse(
                content={
                    "error": "some_error",
                    "details": {"code": code},
                }
            )
            assert (
                executor._should_retry_for_auth_error(chunk) is False
            ), f"Should not detect auth error for code: {code}"

    def test_should_retry_for_auth_error_non_auth_message(self, executor):
        """Test that non-auth messages don't trigger retry."""
        non_auth_messages = [
            "Rate limit exceeded",
            "Model not found",
            "Invalid request format",
            "Server timeout",
            "Network error",
        ]

        for message in non_auth_messages:
            chunk = ProcessedResponse(
                content={
                    "error": "some_error",
                    "message": message,
                    "details": {},
                }
            )
            assert (
                executor._should_retry_for_auth_error(chunk) is False
            ), f"Should not detect auth error for message: {message}"

    def test_should_retry_for_auth_error_combined_heuristics(self, executor):
        """Test detection when multiple heuristics are present."""
        # Status code + code heuristic
        chunk1 = ProcessedResponse(
            content={
                "error": "auth_failed",
                "details": {
                    "status": 401,
                    "code": "invalid_token",
                },
            }
        )
        assert executor._should_retry_for_auth_error(chunk1) is True

        # Status code + message heuristic
        chunk2 = ProcessedResponse(
            content={
                "error": "401 Unauthorized",
                "details": {
                    "status": 403,
                    "message": "Token expired",
                },
            }
        )
        assert executor._should_retry_for_auth_error(chunk2) is True

        # Code + message heuristic (no status code)
        chunk3 = ProcessedResponse(
            content={
                "error": "access_denied",
                "details": {
                    "code": "unauthorized",
                    "message": "401 error occurred",
                },
            }
        )
        assert executor._should_retry_for_auth_error(chunk3) is True

    def test_should_retry_for_auth_error_edge_cases(self, executor):
        """Test edge cases for auth error detection."""
        # Empty content
        chunk1 = ProcessedResponse(content={})
        assert executor._should_retry_for_auth_error(chunk1) is False

        # Non-dict content
        chunk2 = ProcessedResponse(content="string content")
        assert executor._should_retry_for_auth_error(chunk2) is False

        # Chunk without content attribute (raw chunk)
        chunk3 = {"error": "401", "details": {"status": 401}}
        assert executor._should_retry_for_auth_error(chunk3) is True

        # Code as integer status code (should match via status code extraction)
        chunk4 = ProcessedResponse(
            content={
                "details": {"code": 401},  # Integer status code
            }
        )
        # Integer 401 is extracted as a status code and matches auth error
        assert executor._should_retry_for_auth_error(chunk4) is True

        # Code as non-string non-status-code (should not match heuristic)
        chunk4b = ProcessedResponse(
            content={
                "details": {"code": 500},  # Integer, but not auth-related
            }
        )
        assert executor._should_retry_for_auth_error(chunk4b) is False

        # Code as non-string auth-related integer (should match via status code)
        chunk4c = ProcessedResponse(
            content={
                "details": {"code": 403},  # Integer status code
            }
        )
        assert executor._should_retry_for_auth_error(chunk4c) is True

        # Message as non-string (should not match message heuristic)
        chunk5 = ProcessedResponse(
            content={
                "message": {"text": "401 error"},  # Dict, not string
            }
        )
        assert executor._should_retry_for_auth_error(chunk5) is False

    def test_should_retry_for_auth_error_case_insensitive(self, executor):
        """Test that heuristic detection is case-insensitive."""
        # Uppercase code
        chunk1 = ProcessedResponse(
            content={
                "details": {"code": "INVALID_TOKEN"},
            }
        )
        assert executor._should_retry_for_auth_error(chunk1) is True

        # Mixed case message
        chunk2 = ProcessedResponse(
            content={
                "error": "401 UnAuThOrIzEd",
            }
        )
        assert executor._should_retry_for_auth_error(chunk2) is True

        # Lowercase with mixed case keyword
        chunk3 = ProcessedResponse(
            content={
                "message": "Token Has Expired",
            }
        )
        assert executor._should_retry_for_auth_error(chunk3) is True

    def test_get_retry_delay(self, executor):
        """Test retry delay calculation."""
        assert executor._get_retry_delay(0) == 0.1
        assert executor._get_retry_delay(1) == 0.2
        assert executor._get_retry_delay(2) == 0.2  # Uses last value
        assert executor._get_retry_delay(-1) == 0.0

    @pytest.mark.asyncio
    async def test_execute_non_streaming_empty_choices_logs_debug(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Test that empty choices are logged at debug level."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "model": "gpt-5.1-codex",
            "choices": [],
        }
        mock_response.headers = {}
        mock_base_connector.client.post = AsyncMock(return_value=mock_response)

        domain_response = MagicMock()
        domain_response.model_dump.return_value = {}
        domain_response.usage = None
        mock_base_connector.translation_service.to_domain_response.return_value = (
            domain_response
        )

        with patch("src.connectors.openai_codex.executor.logger") as mock_logger:
            mock_logger.isEnabledFor.return_value = True
            await executor.execute(non_streaming_payload, sample_context)

            # Should log debug message about empty choices
            mock_logger.debug.assert_called()
