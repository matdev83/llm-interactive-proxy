"""Streaming ResponseExecutor execution tests."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from src.connectors.contracts import ConnectorRequestContext
from src.connectors.openai_codex.continuation import (
    InMemoryCodexContinuationCoordinator,
)
from src.connectors.openai_codex.contracts import (
    CodexPayload,
    CodexToolSchema,
    CompatibilityState,
)
from src.connectors.openai_codex.executor import ResponseExecutor
from src.connectors.openai_codex.interfaces import ICompatibilityLayer
from src.connectors.openai_codex_v2.ws_lineage import CodexWebsocketV2Lineage
from src.core.common.exceptions import InvalidRequestError, RateLimitExceededError
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.translators.responses.streaming import (
    reset_active_responses_stream_context,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.translation_service import TranslationService


class TestResponseExecutor:
    """Test ResponseExecutor service implementation."""

    @pytest.mark.asyncio
    async def test_execute_non_streaming_payload_still_uses_streaming_transport(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        """Executor should always use streaming transport even for non-stream payloads."""

        async def empty_iterator():
            return
            yield  # pragma: no cover

        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {"x-request-id": "stream-123"}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = empty_iterator()
        mock_base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert isinstance(result, StreamingResponseEnvelope)
        assert result.content is not None
        async for _ in result.content:
            pass

        mock_base_connector._handle_streaming_response.assert_awaited_once()
        mock_base_connector.client.post.assert_not_called()

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
        assert result.content is not None
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
        assert result.content is not None
        async for _ in result.content:
            pass
        # Should have attempted refresh once (on first 401)
        assert mock_credential_manager.refresh_access_token.call_count >= 1

    @pytest.mark.asyncio
    async def test_execute_streaming_handshake_rate_limit_rotation_retry(
        self, executor, mock_base_connector, sample_context, streaming_payload
    ):
        """Streaming handshake 429 should rotate managed account and retry."""

        async def empty_iterator():
            return
            yield  # pragma: no cover

        success_handle = MagicMock()
        success_handle.headers = {}
        success_handle.cancel_callback = AsyncMock()
        success_handle.iterator = empty_iterator()

        call_count = [0]

        async def handle_streaming_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise HTTPException(status_code=429, detail="rate limited")
            return success_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=True)

        result = await executor.execute(streaming_payload, sample_context)

        assert isinstance(result, StreamingResponseEnvelope)
        assert result.content is not None
        async for _ in result.content:
            pass

        mock_base_connector._handle_rate_limit_rotation.assert_awaited_once_with(
            None,
            session_id=sample_context.session_id,
            upstream_codex_error=None,
            response_headers=None,
        )

    @pytest.mark.asyncio
    async def test_execute_streaming_rotation_invalidates_continuation(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id.return_value = "resp-prev"

        async def empty_iterator():
            return
            yield  # pragma: no cover

        success_handle = MagicMock()
        success_handle.headers = {}
        success_handle.cancel_callback = AsyncMock()
        success_handle.iterator = empty_iterator()

        call_count = [0]

        async def handle_streaming_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise HTTPException(status_code=429, detail="rate limited")
            return success_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=True)

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        async for _ in result.content:
            pass

        continuation.invalidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_streaming_auth_rotation_invalidates_continuation(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id.return_value = "resp-prev"

        async def empty_iterator():
            return
            yield  # pragma: no cover

        success_handle = MagicMock()
        success_handle.headers = {}
        success_handle.cancel_callback = AsyncMock()
        success_handle.iterator = empty_iterator()

        call_count = [0]

        async def handle_streaming_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise HTTPException(status_code=403, detail="Forbidden")
            return success_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )
        mock_base_connector._handle_forbidden_rotation = AsyncMock(return_value=True)

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        async for _ in result.content:
            pass

        continuation.invalidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_streaming_handshake_maps_instruction_invalid_error(
        self, executor, mock_base_connector, sample_context, streaming_payload
    ):
        """Handshake instruction validation failures should use actionable Codex error mapping."""

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=HTTPException(
                status_code=400,
                detail={"detail": "Instructions are not valid"},
            )
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None

        with pytest.raises(HTTPException) as exc_info:
            async for _ in result.content:
                pass

        assert exc_info.value.status_code == 400
        assert isinstance(exc_info.value.detail, dict)
        detail = exc_info.value.detail
        assert detail.get("error") == "codex_instructions_invalid"
        assert "prompt_mode" in str(detail.get("suggestion", ""))

    @pytest.mark.asyncio
    async def test_execute_streaming_handshake_uses_retry_after_from_error_detail(
        self, executor, mock_base_connector, sample_context, streaming_payload
    ):
        """Streaming handshake 429 should forward retry_after from error details."""

        async def empty_iterator():
            return
            yield  # pragma: no cover

        success_handle = MagicMock()
        success_handle.headers = {}
        success_handle.cancel_callback = AsyncMock()
        success_handle.iterator = empty_iterator()

        call_count = [0]

        async def handle_streaming_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise HTTPException(
                    status_code=429,
                    detail={"error": {"retry_after_seconds": 45}},
                )
            return success_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=True)

        result = await executor.execute(streaming_payload, sample_context)

        assert isinstance(result, StreamingResponseEnvelope)
        assert result.content is not None
        async for _ in result.content:
            pass

        mock_base_connector._handle_rate_limit_rotation.assert_awaited_once_with(
            45.0,
            session_id=sample_context.session_id,
            upstream_codex_error={"error": {"retry_after_seconds": 45}},
            response_headers=None,
        )

    @pytest.mark.asyncio
    async def test_execute_streaming_handshake_429_rotates_when_effective_max_retries_zero(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        """429 quota rotation must run once even when effective streaming retry budget is 0."""
        mock_credential_manager.effective_max_rate_limit_retries = AsyncMock(
            return_value=0
        )

        async def empty_iterator():
            return
            yield  # pragma: no cover

        success_handle = MagicMock()
        success_handle.headers = {}
        success_handle.cancel_callback = AsyncMock()
        success_handle.iterator = empty_iterator()

        call_count = [0]

        async def handle_streaming_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise HTTPException(
                    status_code=429,
                    detail={"error": {"retry_after_seconds": 30}},
                )
            return success_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=True)

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            max_retries=0,
            retry_backoff_seconds=(0.01,),
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        async for _ in result.content:
            pass

        mock_base_connector._handle_rate_limit_rotation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_streaming_second_handshake_429_marks_accounts_not_exhausted_when_no_budget(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        """After one 429 rotation, a second 429 with no remaining budget is not 'all exhausted'."""
        mock_credential_manager.effective_max_rate_limit_retries = AsyncMock(
            return_value=0
        )
        mock_credential_manager.notify_codex_usage_limit_unrecovered = AsyncMock()

        async def handle_streaming_side_effect(*args, **kwargs):
            raise HTTPException(
                status_code=429,
                detail={"error": {"retry_after_seconds": 10}},
            )

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=True)

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            max_retries=0,
            retry_backoff_seconds=(0.01,),
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        with pytest.raises(HTTPException) as exc_info:
            async for _ in result.content:
                pass

        assert exc_info.value.status_code == 429
        mock_base_connector._handle_rate_limit_rotation.assert_awaited_once()
        mock_credential_manager.notify_codex_usage_limit_unrecovered.assert_awaited_once()
        notify_await_args = (
            mock_credential_manager.notify_codex_usage_limit_unrecovered.await_args
        )
        assert notify_await_args is not None
        assert notify_await_args.kwargs["pool_exhaustion_confirmed"] is False

    @pytest.mark.asyncio
    async def test_execute_streaming_handshake_429_usage_limit_notifies_when_rotation_exhausted(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ):
        """Streaming handshake 429 with usage_limit must notify when rotation cannot recover."""
        mock_credential_manager.effective_max_rate_limit_retries = AsyncMock(
            return_value=1
        )
        mock_credential_manager.notify_codex_usage_limit_unrecovered = AsyncMock()

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            max_retries=2,
            retry_backoff_seconds=(0.01,),
        )
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=False)

        detail = {
            "error": {
                "type": "usage_limit_reached",
                "message": "The usage limit has been reached",
                "plan_type": "plus",
                "resets_in_seconds": 120,
            }
        }
        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=HTTPException(status_code=429, detail=detail)
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        with pytest.raises(HTTPException) as exc_info:
            async for _ in result.content:
                pass

        assert exc_info.value.status_code == 429
        mock_credential_manager.notify_codex_usage_limit_unrecovered.assert_awaited_once()
        await_args = (
            mock_credential_manager.notify_codex_usage_limit_unrecovered.await_args
        )
        assert await_args is not None
        notify_kw = cast(dict[str, Any], await_args.kwargs)
        assert notify_kw["upstream_detail"] == detail
        assert notify_kw["pool_exhaustion_confirmed"] is True

    @pytest.mark.asyncio
    async def test_execute_streaming_iterator_rate_limit_rotation_retry(
        self, executor, mock_base_connector, sample_context, streaming_payload
    ) -> None:
        """Iterator-time 429 before visible output should rotate managed account and retry."""

        async def failing_iterator():
            raise RateLimitExceededError(
                "WebSocket error: The usage limit has been reached",
                details={
                    "code": "usage_limit_reached",
                    "message": "The usage limit has been reached",
                    "retry_after_seconds": 60,
                },
            )
            yield  # pragma: no cover

        async def success_iterator():
            return
            yield  # pragma: no cover

        failing_handle = MagicMock()
        failing_handle.headers = {}
        failing_handle.cancel_callback = AsyncMock()
        failing_handle.iterator = failing_iterator()

        success_handle = MagicMock()
        success_handle.headers = {}
        success_handle.cancel_callback = AsyncMock()
        success_handle.iterator = success_iterator()

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=[failing_handle, success_handle]
        )
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=True)

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        async for _ in result.content:
            pass

        assert mock_base_connector._handle_streaming_response.await_count == 2
        mock_base_connector._handle_rate_limit_rotation.assert_awaited_once_with(
            60.0,
            session_id=sample_context.session_id,
            upstream_codex_error={
                "code": "usage_limit_reached",
                "message": "The usage limit has been reached",
                "retry_after_seconds": 60,
            },
            response_headers=None,
        )

    @pytest.mark.asyncio
    async def test_execute_streaming_iterator_rate_limit_does_not_retry_after_visible_output(
        self, executor, mock_base_connector, sample_context, streaming_payload
    ) -> None:
        """Iterator-time 429 after visible output should surface the error without rotation."""

        chunk = ProcessedResponse(
            content={"choices": [{"delta": {"content": "visible output"}}]}
        )

        async def failing_iterator():
            yield chunk
            raise RateLimitExceededError(
                "WebSocket error: The usage limit has been reached",
                details={"message": "The usage limit has been reached"},
            )

        failing_handle = MagicMock()
        failing_handle.headers = {}
        failing_handle.cancel_callback = AsyncMock()
        failing_handle.iterator = failing_iterator()

        mock_base_connector._handle_streaming_response = AsyncMock(
            return_value=failing_handle
        )
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=True)

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None

        received = []
        with pytest.raises(RateLimitExceededError) as exc_info:
            async for item in result.content:
                received.append(item)

        assert received == [chunk]
        assert exc_info.value.status_code == 429
        mock_base_connector._handle_rate_limit_rotation.assert_not_awaited()

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
        assert result.content is not None
        content = result.content
        with pytest.raises(HTTPException) as exc_info:
            async for _ in content:
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
        assert result.content is not None
        chunks = []
        async for chunk in result.content:
            chunks.append(chunk)
        # Should have attempted refresh when auth error detected
        assert mock_credential_manager.refresh_access_token.call_count >= 1
        # Should eventually get successful chunks after retry
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_execute_streaming_does_not_restart_after_tool_output_then_auth_error(
        self,
        executor,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ):
        async def tool_then_auth_error_iterator():
            yield ProcessedResponse(
                content={
                    "type": "response.output_item.added",
                    "item": {"type": "function_call", "name": "apply_patch"},
                }
            )
            yield ProcessedResponse(
                content={
                    "error": "auth_failed",
                    "details": {"status": 401},
                }
            )

        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = tool_then_auth_error_iterator()
        mock_base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )

        result = await executor.execute(streaming_payload, sample_context)

        assert result.content is not None
        chunks = [chunk async for chunk in result.content]

        assert len(chunks) == 2
        assert mock_base_connector._handle_streaming_response.await_count == 1
        assert mock_credential_manager.refresh_access_token.await_count == 0

    @pytest.mark.asyncio
    async def test_execute_streaming_normalizes_responses_tool_completion_events(
        self,
        executor,
        mock_base_connector,
        sample_context,
        streaming_payload,
    ):
        mock_base_connector.translation_service = TranslationService()
        reset_active_responses_stream_context()

        full_arguments = '{"command":["bash","-lc","git log -1 --oneline"]}'

        async def websocket_style_iterator():
            yield ProcessedResponse(
                content={
                    "type": "response.created",
                    "response": {"id": "resp_ws_tool", "model": "gpt-5.1-codex"},
                },
                metadata={"event_type": "response.created"},
            )
            yield ProcessedResponse(
                content={
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_ws_tool",
                    "output_index": 1,
                    "delta": full_arguments,
                },
                metadata={"event_type": "response.function_call_arguments.delta"},
            )
            yield ProcessedResponse(
                content={
                    "type": "response.output_item.done",
                    "output_index": 1,
                    "item": {
                        "id": "fc_ws_tool",
                        "type": "function_call",
                        "name": "shell",
                        "arguments": "{}",
                    },
                },
                metadata={"event_type": "response.output_item.done"},
            )

        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = websocket_style_iterator()
        mock_base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )

        result = await executor.execute(streaming_payload, sample_context)

        assert result.content is not None
        chunks = [chunk async for chunk in result.content]

        tool_chunks = [
            chunk
            for chunk in chunks
            if isinstance(chunk.content, dict)
            and isinstance(chunk.content.get("choices"), list)
            and chunk.content["choices"]
            and isinstance(chunk.content["choices"][0], dict)
            and isinstance(chunk.content["choices"][0].get("delta"), dict)
            and chunk.content["choices"][0]["delta"].get("tool_calls")
        ]

        assert tool_chunks, "expected canonical tool-call chunk from Responses events"
        tool_call = tool_chunks[-1].content["choices"][0]["delta"]["tool_calls"][0]
        assert tool_call["function"]["name"] == "bash"
        assert "git log -1 --oneline" in tool_call["function"]["arguments"]

    @pytest.mark.asyncio
    async def test_execute_streaming_normalizes_response_done_into_stop_chunk(
        self,
        executor,
        mock_base_connector,
        sample_context,
        streaming_payload,
    ):
        mock_base_connector.translation_service = TranslationService()
        reset_active_responses_stream_context()

        async def websocket_style_iterator():
            yield ProcessedResponse(
                content={
                    "type": "response.created",
                    "response": {"id": "resp_ws_done", "model": "gpt-5.1-codex"},
                },
                metadata={"event_type": "response.created"},
            )
            yield ProcessedResponse(
                content={
                    "id": "resp_ws_done",
                    "output": [],
                    "usage": {"input_tokens": 7, "output_tokens": 3},
                },
                metadata={"event_type": "response.done", "done": True},
            )

        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = websocket_style_iterator()
        mock_base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )

        result = await executor.execute(streaming_payload, sample_context)

        assert result.content is not None
        chunks = [chunk async for chunk in result.content]

        final_chunk = chunks[-1]
        assert final_chunk.metadata["done"] is True
        assert isinstance(final_chunk.content, dict)
        assert final_chunk.content["id"] == "resp_ws_done"
        assert final_chunk.content["choices"][0]["finish_reason"] == "stop"

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
        assert result.content is not None
        content = result.content
        with pytest.raises(HTTPException) as exc_info:
            async for _ in content:
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
        assert result.content is not None
        content = result.content
        with pytest.raises(HTTPException) as exc_info:
            async for _ in content:
                pass

        assert exc_info.value.status_code == 401
        assert "openai_codex_stream_auth_failed" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_execute_streaming_handshake_refresh_exception_is_handled(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        """Unexpected refresh exceptions should not escape from auth-retry handling."""
        executor_with_retries = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            max_retries=1,
            retry_backoff_seconds=(0.1,),
        )

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=HTTPException(status_code=401, detail="Unauthorized")
        )
        mock_credential_manager.refresh_access_token = AsyncMock(
            side_effect=RuntimeError("refresh boom")
        )

        result = await executor_with_retries.execute(streaming_payload, sample_context)
        assert result.content is not None

        with pytest.raises(HTTPException) as exc_info:
            async for _ in result.content:
                pass

        assert exc_info.value.status_code == 401
        assert "openai_codex_stream_auth_failed" in str(exc_info.value.detail)

    async def test_execute_streaming_retries_incompatible_tool_call_before_output(
        self, executor, sample_context, streaming_payload
    ):
        """Unsupported tool calls should restart stream before any chunk is emitted."""
        compatibility_layer = MagicMock(spec=ICompatibilityLayer)
        compatibility_layer.detect_incompatible_tool_calls.return_value = [
            "apply_patch"
        ]
        compatibility_layer.append_incompatible_tool_steering.side_effect = (
            lambda payload_dict, incompatible_tools, context: {
                **payload_dict,
                "instructions": "retry steering",
            }
        )
        executor._compatibility_layer = compatibility_layer

        first_handle = MagicMock()
        first_handle.headers = {}
        first_handle.cancel_callback = AsyncMock()

        async def first_iterator():
            yield ProcessedResponse(
                content={
                    "type": "response.output_item.added",
                    "item": {"type": "function_call", "name": "apply_patch"},
                }
            )

        first_handle.iterator = first_iterator()

        second_handle = MagicMock()
        second_handle.headers = {}
        second_handle.cancel_callback = AsyncMock()

        async def second_iterator():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "ok"}}]},
                metadata={},
            )

        second_handle.iterator = second_iterator()

        captured_payloads: list[dict[str, object]] = []

        async def streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            captured_payloads.append(dict(payload_dict))
            if len(captured_payloads) == 1:
                return first_handle
            return second_handle

        executor._base_connector._handle_streaming_response = AsyncMock(
            side_effect=streaming_side_effect
        )

        result = await executor.execute(streaming_payload, sample_context)
        chunks = [
            chunk
            async for chunk in cast(AsyncIterator[ProcessedResponse], result.content)
        ]

        assert len(chunks) == 1
        assert chunks[0].content == {"choices": [{"delta": {"content": "ok"}}]}
        assert len(captured_payloads) == 2
        assert captured_payloads[1]["instructions"] == "retry steering"
        first_handle.cancel_callback.assert_awaited()
        compatibility_layer.append_incompatible_tool_steering.assert_called_once()

    async def test_execute_streaming_logs_retry_cancellation_reason(
        self, executor, sample_context, streaming_payload, caplog
    ) -> None:
        compatibility_layer = MagicMock(spec=ICompatibilityLayer)
        compatibility_layer.detect_incompatible_tool_calls.return_value = [
            "apply_patch"
        ]
        compatibility_layer.append_incompatible_tool_steering.side_effect = (
            lambda payload_dict, incompatible_tools, context: {
                **payload_dict,
                "instructions": "retry steering",
            }
        )
        executor._compatibility_layer = compatibility_layer

        first_handle = MagicMock()
        first_handle.headers = {}
        first_handle.cancel_callback = AsyncMock()

        async def first_iterator():
            yield ProcessedResponse(
                content={
                    "id": "resp_retry_123",
                    "type": "response.output_item.added",
                    "item": {"type": "function_call", "name": "apply_patch"},
                }
            )

        first_handle.iterator = first_iterator()

        second_handle = MagicMock()
        second_handle.headers = {}
        second_handle.cancel_callback = AsyncMock()

        async def second_iterator():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "ok"}}]},
                metadata={},
            )

        second_handle.iterator = second_iterator()

        async def streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            if payload_dict.get("instructions") == "retry steering":
                return second_handle
            return first_handle

        executor._base_connector._handle_streaming_response = AsyncMock(
            side_effect=streaming_side_effect
        )

        with caplog.at_level(logging.INFO):
            result = await executor.execute(streaming_payload, sample_context)
            chunks = [
                chunk
                async for chunk in cast(
                    AsyncIterator[ProcessedResponse], result.content
                )
            ]

        assert len(chunks) == 1
        matching = [
            record
            for record in caplog.records
            if str(record.msg).startswith("Cancelling active Codex stream for retry")
        ]
        assert matching
        assert matching[-1].retry_reason == "incompatible_tools"
        assert matching[-1].response_id == "resp_retry_123"

    async def test_execute_streaming_retries_incompatible_tool_call_after_text_output(
        self, executor, sample_context, streaming_payload
    ) -> None:
        """Incompatible tool retries should still fire even after brief text output."""
        compatibility_layer = MagicMock(spec=ICompatibilityLayer)
        compatibility_layer.detect_incompatible_tool_calls.return_value = [
            "apply_patch"
        ]
        compatibility_layer.append_incompatible_tool_steering.side_effect = (
            lambda payload_dict, incompatible_tools, context: {
                **payload_dict,
                "instructions": "retry steering",
            }
        )
        executor._compatibility_layer = compatibility_layer

        first_handle = MagicMock()
        first_handle.headers = {}
        first_handle.cancel_callback = AsyncMock()

        async def first_iterator():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "Working on it."}}]},
                metadata={},
            )
            yield ProcessedResponse(
                content={
                    "type": "response.output_item.added",
                    "item": {"type": "function_call", "name": "apply_patch"},
                }
            )

        first_handle.iterator = first_iterator()

        second_handle = MagicMock()
        second_handle.headers = {}
        second_handle.cancel_callback = AsyncMock()

        async def second_iterator():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "Using native edit."}}]},
                metadata={},
            )

        second_handle.iterator = second_iterator()

        captured_payloads: list[dict[str, object]] = []

        async def streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            captured_payloads.append(dict(payload_dict))
            if len(captured_payloads) == 1:
                return first_handle
            return second_handle

        executor._base_connector._handle_streaming_response = AsyncMock(
            side_effect=streaming_side_effect
        )

        result = await executor.execute(streaming_payload, sample_context)
        chunks = [
            chunk
            async for chunk in cast(AsyncIterator[ProcessedResponse], result.content)
        ]

        assert len(chunks) == 2
        assert chunks[0].content == {
            "choices": [{"delta": {"content": "Working on it."}}]
        }
        assert chunks[1].content == {
            "choices": [{"delta": {"content": "Using native edit."}}]
        }
        assert len(captured_payloads) == 2
        assert captured_payloads[1]["instructions"] == "retry steering"
        first_handle.cancel_callback.assert_awaited()
        compatibility_layer.append_incompatible_tool_steering.assert_called_once()

    async def test_conversation_id_preserved_across_streaming_retries(
        self,
        executor,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ):
        """Test that conversation_id is preserved across streaming retries (Req 1.2, 6.1, 6.2)."""
        # Set prompt_cache_key in payload
        streaming_payload.prompt_cache_key = "retry-conversation-key-456"

        # Track headers passed to _handle_streaming_response across retries
        captured_headers_list = []

        async def empty_iterator():
            return
            yield  # Make it an async generator

        success_handle = MagicMock()
        success_handle.headers = {}
        success_handle.cancel_callback = AsyncMock()
        success_handle.iterator = empty_iterator()

        # First attempt fails with 401, second succeeds
        call_count = [0]

        async def handle_streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            # Capture headers from the call (public interface - headers passed to HTTP transport)
            if headers:
                captured_headers_list.append(headers.copy())
            call_count[0] += 1
            if call_count[0] == 1:
                raise HTTPException(status_code=401, detail="Unauthorized")
            return success_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        result = await executor.execute(streaming_payload, sample_context)

        # Consume stream to trigger retry logic
        async for _ in result.content:
            pass

        # Verify conversation_id was consistent across retries
        # Headers are captured from _handle_streaming_response calls (public transport interface)
        assert (
            len(captured_headers_list) >= 2
        ), f"Expected at least 2 header captures (initial + retry), got {len(captured_headers_list)}"
        conversation_ids = [h.get("conversation_id") for h in captured_headers_list]
        # All conversation_ids should match prompt_cache_key
        assert all(
            cid == "retry-conversation-key-456" for cid in conversation_ids
        ), f"Expected all conversation_ids to be 'retry-conversation-key-456', got {conversation_ids}"

    @pytest.mark.asyncio
    async def test_execute_streaming_http_omits_previous_response_id_from_continuation(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id.return_value = "resp_prev_123"

        async def done_iterator():
            yield ProcessedResponse(
                content={"id": "resp_new_456", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        captured_payloads: list[dict[str, object]] = []
        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = done_iterator()

        async def handle_streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            captured_payloads.append(dict(payload_dict))
            return mock_stream_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        async for _ in result.content:
            pass

        assert "previous_response_id" not in captured_payloads[0]
        continuation.resolve_previous_response_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_streaming_http_full_replay_keeps_bootstrap_fields(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id.return_value = "resp_prev_123"
        streaming_payload.instructions = "Full Codex bootstrap"
        streaming_payload.tools = [
            CodexToolSchema(
                name="read_file",
                description="Read a file",
                type="function",
                parameters={"type": "object", "properties": {}},
            )
        ]

        async def done_iterator():
            yield ProcessedResponse(
                content={"id": "resp_new_456", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        captured_payloads: list[dict[str, object]] = []
        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = done_iterator()

        async def handle_streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            captured_payloads.append(dict(payload_dict))
            return mock_stream_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        async for _ in result.content:
            pass

        assert "previous_response_id" not in captured_payloads[0]
        assert captured_payloads[0]["instructions"] == "Full Codex bootstrap"
        tools = captured_payloads[0]["tools"]
        assert isinstance(tools, list)
        assert tools[0]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_execute_streaming_logs_continuation_mode_metrics(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
        caplog,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id.return_value = "resp_prev_123"
        streaming_payload.instructions = "Full Codex bootstrap"
        streaming_payload.tools = [
            CodexToolSchema(
                name="read_file",
                description="Read a file",
                type="function",
                parameters={"type": "object", "properties": {}},
            )
        ]

        async def done_iterator():
            yield ProcessedResponse(
                content={"id": "resp_new_456", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = done_iterator()
        mock_base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        with caplog.at_level(logging.INFO):
            result = await executor.execute(streaming_payload, sample_context)
            assert result.content is not None
            async for _ in result.content:
                pass

        matching = [
            record
            for record in caplog.records
            if str(record.msg).startswith("Submitting Codex request")
        ]
        assert matching
        assert matching[-1].continuation_mode == "http_bootstrap"
        assert matching[-1].continuation_reason == "http_bootstrap"
        assert matching[-1].codex_transport == "http_sse"
        assert matching[-1].input_item_count == 0
        assert matching[-1].instructions_bytes > 0
        assert matching[-1].tools_bytes > 0

    @pytest.mark.asyncio
    async def test_execute_streaming_logs_bootstrap_reason_when_no_continuation_exists(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
        caplog,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id.return_value = None

        async def done_iterator():
            yield ProcessedResponse(
                content={"id": "resp_new_456", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = done_iterator()
        mock_base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        with caplog.at_level(logging.INFO):
            result = await executor.execute(streaming_payload, sample_context)
            assert result.content is not None
            async for _ in result.content:
                pass

        matching = [
            record
            for record in caplog.records
            if str(record.msg).startswith("Submitting Codex request")
        ]
        assert matching
        assert matching[-1].continuation_mode == "http_bootstrap"
        assert matching[-1].continuation_reason == "http_bootstrap"
        assert matching[-1].codex_transport == "http_sse"

    @pytest.mark.asyncio
    async def test_execute_streaming_http_second_turn_full_replay_without_previous_response_id(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
    ) -> None:
        continuation = InMemoryCodexContinuationCoordinator()
        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        from src.connectors.openai_codex.contracts import CodexInputItem, CodexPayload

        first_payload = CodexPayload(
            model="gpt-5.1-codex",
            input=[
                CodexInputItem.model_validate(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "environment block"}
                        ],
                    }
                ),
                CodexInputItem.model_validate(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "turn one"}],
                    }
                ),
            ],
            tools=[
                CodexToolSchema(
                    name="read_file",
                    description="Read a file",
                    type="function",
                    parameters={"type": "object", "properties": {}},
                )
            ],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=True,
            include=[],
            prompt_cache_key="test-key",
            instructions="Full Codex bootstrap",
        )

        second_payload = first_payload.model_copy(
            update={
                "input": [
                    *first_payload.input,
                    CodexInputItem.model_validate(
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "turn one reply"}
                            ],
                        }
                    ),
                    CodexInputItem.model_validate(
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "turn two"}],
                        }
                    ),
                ]
            }
        )

        async def first_iterator():
            yield ProcessedResponse(
                content={"id": "resp_first", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        async def second_iterator():
            yield ProcessedResponse(
                content={"id": "resp_second", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        captured_payloads: list[dict[str, object]] = []

        async def handle_streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            captured_payloads.append(dict(payload_dict))
            stream_handle = MagicMock()
            stream_handle.headers = {}
            stream_handle.cancel_callback = AsyncMock()
            stream_handle.iterator = (
                first_iterator() if len(captured_payloads) == 1 else second_iterator()
            )
            return stream_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        first_result = await executor.execute(first_payload, sample_context)
        assert first_result.content is not None
        async for _ in first_result.content:
            pass

        second_result = await executor.execute(second_payload, sample_context)
        assert second_result.content is not None
        async for _ in second_result.content:
            pass

        assert len(captured_payloads) == 2
        assert "previous_response_id" not in captured_payloads[0]
        assert "previous_response_id" not in captured_payloads[1]
        assert captured_payloads[1]["instructions"] == "Full Codex bootstrap"
        tools = captured_payloads[1]["tools"]
        assert isinstance(tools, list)
        assert tools[0]["name"] == "read_file"
        second_input = captured_payloads[1]["input"]
        assert isinstance(second_input, list)
        assert second_input == [
            item.model_dump(exclude_none=True) for item in second_payload.input
        ]

    @pytest.mark.asyncio
    async def test_execute_streaming_invalidates_proxy_lineage_on_tool_change(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
    ) -> None:
        continuation = InMemoryCodexContinuationCoordinator()
        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )
        from src.connectors.openai_codex.contracts import CodexInputItem, CodexPayload

        first_payload = CodexPayload(
            model="gpt-5.1-codex",
            input=[
                CodexInputItem.model_validate(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "turn one"}],
                    }
                )
            ],
            tools=[
                CodexToolSchema(
                    name="read_file",
                    description="Read a file",
                    type="function",
                    parameters={"type": "object", "properties": {}},
                )
            ],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=True,
            include=[],
            prompt_cache_key="test-key",
            instructions="Full Codex bootstrap",
        )
        changed_tool_payload = first_payload.model_copy(
            update={
                "tools": [
                    CodexToolSchema(
                        name="write_file",
                        description="Write a file",
                        type="function",
                        parameters={"type": "object", "properties": {}},
                    )
                ],
                "input": [
                    *first_payload.input,
                    CodexInputItem.model_validate(
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "turn two"}],
                        }
                    ),
                ],
            }
        )

        async def done_iterator(response_id: str):
            yield ProcessedResponse(
                content={"id": response_id, "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        captured_payloads: list[dict[str, object]] = []

        async def handle_streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            captured_payloads.append(dict(payload_dict))
            stream_handle = MagicMock()
            stream_handle.headers = {}
            stream_handle.cancel_callback = AsyncMock()
            stream_handle.iterator = done_iterator(
                "resp_first" if len(captured_payloads) == 1 else "resp_second"
            )
            return stream_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        first_result = await executor.execute(first_payload, sample_context)
        assert first_result.content is not None
        async for _ in first_result.content:
            pass

        second_result = await executor.execute(changed_tool_payload, sample_context)
        assert second_result.content is not None
        async for _ in second_result.content:
            pass

        assert len(captured_payloads) == 2
        assert "previous_response_id" not in captured_payloads[1]
        changed_tools = captured_payloads[1]["tools"]
        assert isinstance(changed_tools, list)
        assert changed_tools[0]["name"] == "write_file"
        assert captured_payloads[1]["instructions"] == "Full Codex bootstrap"

    @pytest.mark.asyncio
    async def test_execute_streaming_replays_when_history_diverges_mid_conversation(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
    ) -> None:
        continuation = InMemoryCodexContinuationCoordinator()
        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )
        from src.connectors.openai_codex.contracts import CodexInputItem, CodexPayload

        first_payload = CodexPayload(
            model="gpt-5.1-codex",
            input=[
                CodexInputItem.model_validate(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "A"}],
                    }
                ),
                CodexInputItem.model_validate(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "B"}],
                    }
                ),
                CodexInputItem.model_validate(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "C"}],
                    }
                ),
            ],
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=True,
            include=[],
            prompt_cache_key="test-key",
            instructions="Full Codex bootstrap",
        )
        diverged_payload = first_payload.model_copy(
            update={
                "input": [
                    first_payload.input[0],
                    first_payload.input[1],
                    CodexInputItem.model_validate(
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "X"}],
                        }
                    ),
                    CodexInputItem.model_validate(
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "D"}],
                        }
                    ),
                    CodexInputItem.model_validate(
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "E"}],
                        }
                    ),
                ]
            }
        )

        async def done_iterator(response_id: str):
            yield ProcessedResponse(
                content={"id": response_id, "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        captured_payloads: list[dict[str, object]] = []

        async def handle_streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            captured_payloads.append(dict(payload_dict))
            stream_handle = MagicMock()
            stream_handle.headers = {}
            stream_handle.cancel_callback = AsyncMock()
            stream_handle.iterator = done_iterator(
                "resp_first" if len(captured_payloads) == 1 else "resp_second"
            )
            return stream_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        first_result = await executor.execute(first_payload, sample_context)
        assert first_result.content is not None
        async for _ in first_result.content:
            pass

        second_result = await executor.execute(diverged_payload, sample_context)
        assert second_result.content is not None
        async for _ in second_result.content:
            pass

        assert len(captured_payloads) == 2
        assert "previous_response_id" not in captured_payloads[1]
        assert captured_payloads[1]["instructions"] == "Full Codex bootstrap"
        assert captured_payloads[1]["input"] == [
            item.model_dump(exclude_none=True) for item in diverged_payload.input
        ]

    @pytest.mark.asyncio
    async def test_execute_streaming_records_terminal_response_id_in_continuation(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id.return_value = None

        async def done_iterator():
            yield ProcessedResponse(
                content={"id": "resp_terminal_789", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = done_iterator()
        mock_base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        async for _ in result.content:
            pass

        continuation.record_response_id.assert_called_once()
        record_call = continuation.record_response_id.call_args
        assert record_call.args[1] == "resp_terminal_789"

    @pytest.mark.asyncio
    async def test_execute_streaming_records_terminal_response_id_from_translated_http_stop_chunk(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id.return_value = None

        async def done_iterator():
            yield ProcessedResponse(
                content={
                    "choices": [{"delta": {}, "finish_reason": "stop"}],
                    "response_id": "resp_http_terminal_456",
                }
            )

        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = done_iterator()
        mock_base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        async for _ in result.content:
            pass

        continuation.record_response_id.assert_called_once()
        record_call = continuation.record_response_id.call_args
        assert record_call.args[1] == "resp_http_terminal_456"

    @pytest.mark.asyncio
    async def test_execute_streaming_preserves_observed_response_id_when_stream_ends_without_terminal_chunk(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
        caplog,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id.return_value = None

        async def truncated_iterator():
            yield ProcessedResponse(
                content={
                    "id": "resp_observed_123",
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_123",
                                        "type": "function",
                                        "function": {
                                            "name": "read",
                                            "arguments": "",
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )

        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = truncated_iterator()
        mock_base_connector._handle_streaming_response = AsyncMock(
            return_value=mock_stream_handle
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        with caplog.at_level(logging.INFO):
            result = await executor.execute(streaming_payload, sample_context)
            assert result.content is not None
            async for _ in result.content:
                pass

        continuation.record_response_id.assert_called_once()
        assert continuation.record_response_id.call_args.args[1] == "resp_observed_123"
        continuation.record_turn.assert_called_once()
        assert (
            continuation.record_turn.call_args.kwargs["response_id"]
            == "resp_observed_123"
        )
        matching = [
            record
            for record in caplog.records
            if "observed response id remains available for continuation"
            in str(record.msg)
        ]
        assert matching

    @pytest.mark.asyncio
    async def test_execute_streaming_persists_observed_response_id_immediately_for_followup_turn(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
    ) -> None:
        continuation = InMemoryCodexContinuationCoordinator()
        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        from src.connectors.openai_codex.contracts import CodexInputItem, CodexPayload

        first_payload = CodexPayload(
            model="gpt-5.4-mini",
            input=[
                CodexInputItem.model_validate(
                    {
                        "type": "message",
                        "role": "developer",
                        "content": [{"type": "input_text", "text": "bootstrap"}],
                    }
                ),
                CodexInputItem.model_validate(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": "turn one"}],
                    }
                ),
            ],
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=True,
            include=[],
            prompt_cache_key="test-key",
            instructions="Full Codex bootstrap",
        )
        second_payload = first_payload.model_copy(
            update={
                "input": [
                    *first_payload.input,
                    CodexInputItem.model_validate(
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "tool call"}],
                        }
                    ),
                    CodexInputItem.model_validate(
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "turn two"}],
                        }
                    ),
                ]
            }
        )

        first_handle = MagicMock()
        first_handle.headers = {}
        first_handle.cancel_callback = AsyncMock()

        async def first_iterator():
            yield ProcessedResponse(
                content={
                    "id": "resp_observed_midstream",
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {
                                            "name": "read",
                                            "arguments": "",
                                        },
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                }
            )

        first_handle.iterator = first_iterator()

        second_handle = MagicMock()
        second_handle.headers = {}
        second_handle.cancel_callback = AsyncMock()

        async def second_iterator():
            yield ProcessedResponse(
                content={"id": "resp_second", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        second_handle.iterator = second_iterator()

        captured_payloads: list[dict[str, object]] = []

        async def handle_streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            captured_payloads.append(dict(payload_dict))
            return first_handle if len(captured_payloads) == 1 else second_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        first_result = await executor.execute(first_payload, sample_context)
        assert first_result.content is not None
        first_stream = first_result.content
        first_chunk = await anext(first_stream)
        assert isinstance(first_chunk, ProcessedResponse)
        await cast(Any, first_stream).aclose()

        second_result = await executor.execute(second_payload, sample_context)
        assert second_result.content is not None
        async for _ in second_result.content:
            pass

        assert len(captured_payloads) == 2
        assert "previous_response_id" not in captured_payloads[1]
        second_wire_input = captured_payloads[1]["input"]
        assert isinstance(second_wire_input, list)
        assert len(second_wire_input) == len(second_payload.input)

    @pytest.mark.asyncio
    async def test_execute_streaming_invalidates_continuation_on_missing_previous_response(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id.return_value = "resp_prev_missing"

        async def failing_iterator():
            raise InvalidRequestError(
                message="Previous response not found",
                details={"code": "previous_response_not_found"},
            )
            yield  # pragma: no cover

        async def handle_streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            stream_handle = MagicMock()
            stream_handle.headers = {}
            stream_handle.cancel_callback = AsyncMock()
            stream_handle.iterator = failing_iterator()
            return stream_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        with pytest.raises(InvalidRequestError):
            async for _ in result.content:
                pass

        assert continuation.invalidate.call_count >= 1

    @pytest.mark.asyncio
    async def test_execute_streaming_http_does_not_retry_previous_response_miss(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id.return_value = "resp_prev_missing"
        streaming_payload.instructions = "Full Codex bootstrap"
        streaming_payload.tools = [
            CodexToolSchema(
                name="read_file",
                description="Read a file",
                type="function",
                parameters={"type": "object", "properties": {}},
            )
        ]

        async def failing_iterator():
            raise InvalidRequestError(
                message="Previous response not found",
                details={"code": "previous_response_not_found"},
            )
            yield  # pragma: no cover

        first_handle = MagicMock()
        first_handle.headers = {}
        first_handle.cancel_callback = AsyncMock()
        first_handle.iterator = failing_iterator()

        captured_payloads: list[dict[str, object]] = []

        async def handle_streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            captured_payloads.append(dict(payload_dict))
            return first_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        with pytest.raises(InvalidRequestError):
            async for _ in result.content:
                pass

        assert len(captured_payloads) == 1
        assert "previous_response_id" not in captured_payloads[0]
        continuation.resolve_previous_response_id.assert_not_called()
        continuation.invalidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_streaming_http_strips_client_supplied_previous_response_id(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        streaming_payload.previous_response_id = "client-should-not-hit-wire"

        async def done_iterator():
            yield ProcessedResponse(
                content={"id": "resp_ok", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        captured: list[dict[str, object]] = []
        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {}
        mock_stream_handle.cancel_callback = AsyncMock()
        mock_stream_handle.iterator = done_iterator()

        async def capture(url, payload_dict, headers, session_id, *args, **kwargs):
            captured.append(dict(payload_dict))
            return mock_stream_handle

        mock_base_connector._handle_streaming_response = AsyncMock(side_effect=capture)

        executor = ResponseExecutor(mock_base_connector, mock_credential_manager)
        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        async for _ in result.content:
            pass

        assert len(captured) == 1
        assert "previous_response_id" not in captured[0]

    @pytest.mark.asyncio
    async def test_execute_streaming_websocket_resolves_previous_response_id(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
        monkeypatch,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id = AsyncMock(
            return_value="resp_ws_prev"
        )

        async def ws_iterator():
            yield ProcessedResponse(
                content={"id": "resp_ws_terminal", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        ws_client = MagicMock()
        ws_client.disconnect = AsyncMock()
        ws_client.send_response_create = MagicMock(return_value=ws_iterator())

        monkeypatch.setattr(
            "src.connectors.openai_websocket_client.OpenAIWebSocketClient",
            MagicMock(return_value=ws_client),
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
            use_websocket=True,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        async for _ in result.content:
            pass

        continuation.resolve_previous_response_id.assert_awaited_once()
        send_kwargs = ws_client.send_response_create.call_args.kwargs
        assert send_kwargs["previous_response_id"] == "resp_ws_prev"

    @pytest.mark.asyncio
    async def test_execute_streaming_websocket_v2_bootstraps_when_lineage_missing(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
        monkeypatch,
    ) -> None:
        continuation = InMemoryCodexContinuationCoordinator()
        await continuation.record_turn(
            sample_context,
            response_id="resp_ws_prev",
            payload_dict={"input": [{"role": "user", "content": "earlier"}]},
        )

        async def ws_iterator():
            yield ProcessedResponse(
                content={"id": "resp_ws_terminal", "output": []},
                metadata={"event_type": "response.completed", "done": True},
            )

        ws_client = MagicMock()
        ws_client.disconnect = AsyncMock()
        ws_client.send_response_create = MagicMock(return_value=ws_iterator())

        monkeypatch.setattr(
            "src.connectors.openai_websocket_client.OpenAIWebSocketClient",
            MagicMock(return_value=ws_client),
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
            use_websocket=True,
            websocket_beta_mode="v2",
            codex_ws_lineage=CodexWebsocketV2Lineage(continuation),
            preserve_tools_on_managed_ws_continuation=True,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        async for _ in result.content:
            pass

        send_kwargs = ws_client.send_response_create.call_args.kwargs
        assert send_kwargs.get("previous_response_id") is None
        assert send_kwargs["payload"]["input"] == [
            item.model_dump(exclude_none=True) for item in streaming_payload.input
        ]

    @pytest.mark.asyncio
    async def test_execute_streaming_websocket_v2_preserves_lineage_on_early_tool_turn_close(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        monkeypatch,
    ) -> None:
        continuation = InMemoryCodexContinuationCoordinator()
        lineage = CodexWebsocketV2Lineage(continuation)
        first_input: list[dict[str, Any]] = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "inspect repo"}],
            }
        ]
        second_input: list[dict[str, Any]] = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "inspect repo"}],
            },
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "bash",
                "arguments": '{"command":"git status --short"}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "M src/connectors/openai_codex/executor.py",
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "continue"}],
            },
        ]

        first_payload = CodexPayload(
            model="gpt-5.4-mini",
            input=cast(Any, first_input),
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=True,
            include=[],
            prompt_cache_key="test-key",
        )
        second_payload = CodexPayload(
            model="gpt-5.4-mini",
            input=cast(Any, second_input),
            tools=[],
            tool_choice="auto",
            parallel_tool_calls=False,
            store=False,
            stream=True,
            include=[],
            prompt_cache_key="test-key",
        )

        async def first_ws_iterator():
            yield ProcessedResponse(
                content={"response": {"id": "resp_ws_1"}, "type": "response.created"},
                metadata={"event_type": "response.created"},
            )
            yield ProcessedResponse(
                content={
                    "type": "response.output_item.done",
                    "item": {
                        "type": "function_call",
                        "id": "fc_1",
                        "call_id": "call_1",
                        "name": "bash",
                        "arguments": '{"command":"git status --short"}',
                        "status": "completed",
                    },
                },
                metadata={"event_type": "response.output_item.done"},
            )

        async def second_ws_iterator():
            yield ProcessedResponse(
                content={"id": "resp_ws_2", "output": []},
                metadata={"event_type": "response.completed", "done": True},
            )

        send_calls: list[dict[str, Any]] = []

        def send_side_effect(**kwargs: Any):
            send_calls.append(kwargs)
            if len(send_calls) == 1:
                return first_ws_iterator()
            return second_ws_iterator()

        ws_client = MagicMock()
        ws_client.disconnect = AsyncMock()
        ws_client.send_response_create = MagicMock(side_effect=send_side_effect)

        monkeypatch.setattr(
            "src.connectors.openai_websocket_client.OpenAIWebSocketClient",
            MagicMock(return_value=ws_client),
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
            use_websocket=True,
            websocket_beta_mode="v2",
            codex_ws_lineage=lineage,
            preserve_tools_on_managed_ws_continuation=True,
        )

        first_result = await executor.execute(first_payload, sample_context)
        assert first_result.content is not None
        observed_tool_chunk = False
        first_stream = cast(Any, first_result.content)
        async for chunk in first_stream:
            if chunk.metadata.get("event_type") == "response.output_item.done":
                observed_tool_chunk = True
                await first_stream.aclose()
                break

        assert observed_tool_chunk is True

        second_result = await executor.execute(second_payload, sample_context)
        assert second_result.content is not None
        async for _ in second_result.content:
            pass

        assert len(send_calls) == 2
        second_send = send_calls[1]
        assert second_send["previous_response_id"] == "resp_ws_1"
        assert second_send["payload"]["input"] == [
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "M src/connectors/openai_codex/executor.py",
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "continue"}],
            },
        ]

    @pytest.mark.asyncio
    async def test_normalize_processed_stream_chunk_marks_tool_call_emission(
        self,
        mock_base_connector,
        mock_credential_manager,
    ) -> None:
        mock_base_connector.translation_service = TranslationService()
        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
        )

        chunk = ProcessedResponse(
            content={
                "type": "response.output_item.done",
                "output_index": 1,
                "item": {
                    "id": "fc_ws_tool",
                    "type": "function_call",
                    "name": "shell",
                    "arguments": (
                        '{"command":["bash","-lc","git status --short"],'
                        '"description":"Check repository status",'
                        '"timeout":900000,'
                        '"workdir":"C:/Users/Mateusz/source/repos/llm-interactive-proxy"}'
                    ),
                },
            },
            metadata={"event_type": "response.output_item.done"},
        )

        normalized = executor._normalize_processed_stream_chunk(chunk)

        assert normalized.metadata.get("tool_call_emitted") is True
        assert normalized.metadata.get("finish_reason") == "tool_calls"
        content = cast(dict[str, Any], normalized.content)
        assert content["choices"][0]["finish_reason"] == "tool_calls"
        tool_call = content["choices"][0]["delta"]["tool_calls"][0]
        arguments = json.loads(tool_call["function"]["arguments"])
        assert arguments == {
            "command": "bash -lc 'git status --short'",
            "description": "Check repository status",
            "timeout": 900000,
            "workdir": "C:/Users/Mateusz/source/repos/llm-interactive-proxy",
        }

    @pytest.mark.asyncio
    async def test_normalize_processed_stream_chunk_marks_function_call_done_as_tool_output(
        self,
        mock_base_connector,
        mock_credential_manager,
    ) -> None:
        mock_base_connector.translation_service = TranslationService()
        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
        )

        chunk = ProcessedResponse(
            content={
                "type": "response.function_call_arguments.done",
                "item_id": "fc_ws_tool",
                "arguments": '{"command":["bash","-lc","git status --short"]}',
            },
            metadata={"event_type": "response.function_call_arguments.done"},
        )

        normalized = executor._normalize_processed_stream_chunk(chunk)

        assert normalized.metadata.get("tool_call_emitted") is True
        assert normalized.metadata.get("finish_reason") == "tool_calls"
        content = cast(dict[str, Any], normalized.content)
        assert content["choices"][0]["delta"] == {}

    @pytest.mark.asyncio
    async def test_normalize_processed_stream_chunk_preserves_non_shell_timeout_arguments(
        self,
        mock_base_connector,
        mock_credential_manager,
    ) -> None:
        mock_base_connector.translation_service = TranslationService()
        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
        )

        chunk = ProcessedResponse(
            content={
                "type": "response.output_item.done",
                "output_index": 1,
                "item": {
                    "id": "fc_webfetch",
                    "type": "function_call",
                    "name": "webfetch",
                    "arguments": (
                        '{"url":"https://example.com","format":"markdown",'
                        '"timeout":90}'
                    ),
                },
            },
            metadata={"event_type": "response.output_item.done"},
        )

        normalized = executor._normalize_processed_stream_chunk(chunk)

        assert normalized.metadata.get("tool_call_emitted") is True
        content = cast(dict[str, Any], normalized.content)
        tool_call = content["choices"][0]["delta"]["tool_calls"][0]
        assert tool_call["function"]["name"] == "webfetch"
        assert json.loads(tool_call["function"]["arguments"]) == {
            "url": "https://example.com",
            "format": "markdown",
            "timeout": 90,
        }

    @pytest.mark.asyncio
    async def test_normalize_processed_stream_chunk_overrides_falsey_tool_markers(
        self,
        mock_base_connector,
        mock_credential_manager,
    ) -> None:
        mock_base_connector.translation_service = TranslationService()
        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
        )

        chunk = ProcessedResponse(
            content={
                "type": "response.function_call_arguments.done",
                "item_id": "fc_ws_tool",
                "arguments": '{"command":["bash","-lc","git status --short"]}',
            },
            metadata={
                "event_type": "response.function_call_arguments.done",
                "tool_call_emitted": False,
                "finish_reason": None,
            },
        )

        normalized = executor._normalize_processed_stream_chunk(chunk)

        assert normalized.metadata.get("tool_call_emitted") is True
        assert normalized.metadata.get("finish_reason") == "tool_calls"

    @pytest.mark.asyncio
    async def test_normalize_processed_stream_chunk_marks_local_shell_item_done_as_tool_output(
        self,
        mock_base_connector,
        mock_credential_manager,
    ) -> None:
        mock_base_connector.translation_service = TranslationService()
        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
        )

        chunk = ProcessedResponse(
            content={
                "type": "response.output_item.done",
                "item": {
                    "type": "local_shell_call",
                    "id": "shell_1",
                    "call_id": "call_1",
                    "action": {
                        "command": ["bash", "-lc", "git status --short"],
                        "description": "Check repository status",
                        "timeout": 900000,
                        "working_directory": (
                            "C:/Users/Mateusz/source/repos/llm-interactive-proxy"
                        ),
                    },
                },
            },
            metadata={"event_type": "response.output_item.done"},
        )

        normalized = executor._normalize_processed_stream_chunk(chunk)

        assert normalized.metadata.get("tool_call_emitted") is True
        assert normalized.metadata.get("finish_reason") == "tool_calls"
        content = cast(dict[str, Any], normalized.content)
        tool_call = content["choices"][0]["delta"]["tool_calls"][0]
        assert tool_call["function"]["name"] == "bash"
        arguments = json.loads(tool_call["function"]["arguments"])
        assert arguments == {
            "command": "bash -lc 'git status --short'",
            "description": "Check repository status",
            "timeout": 900000,
            "workdir": "C:/Users/Mateusz/source/repos/llm-interactive-proxy",
        }

    @pytest.mark.asyncio
    async def test_execute_streaming_websocket_does_not_persist_provisional_lineage_on_tool_call_only_turn(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
        monkeypatch,
    ) -> None:
        sample_context.metadata = {"compatibility_state": CompatibilityState()}
        mock_base_connector.translation_service = TranslationService()
        continuation = InMemoryCodexContinuationCoordinator()
        ws_lineage = CodexWebsocketV2Lineage(continuation)

        async def ws_stream():
            yield ProcessedResponse(
                content={
                    "type": "response.created",
                    "response": {"id": "resp_ws_tool_only", "model": "gpt-5.4-mini"},
                },
                metadata={"event_type": "response.created"},
            )
            yield ProcessedResponse(
                content={
                    "type": "response.output_item.done",
                    "output_index": 1,
                    "item": {
                        "id": "fc_ws_tool_only",
                        "type": "function_call",
                        "name": "bash",
                        "call_id": "call_ws_tool_only",
                        "arguments": '{"command":"git status --short --untracked-files=all"}',
                    },
                },
                metadata={"event_type": "response.output_item.done"},
            )

        ws_client = MagicMock()
        ws_client.disconnect = AsyncMock()
        ws_client.send_response_create = MagicMock(return_value=ws_stream())

        monkeypatch.setattr(
            "src.connectors.openai_websocket_client.OpenAIWebSocketClient",
            MagicMock(return_value=ws_client),
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
            use_websocket=True,
            websocket_beta_mode="v2",
            codex_ws_lineage=ws_lineage,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        chunks = [c async for c in result.content]

        assert len(chunks) == 2
        previous_response_id = await continuation.resolve_previous_response_id(
            sample_context
        )
        assert previous_response_id is None
        handled, prepared_payload, reason, proxy_managed = (
            await ws_lineage.try_prepare_websocket_continuation(
                continuation_context=sample_context,
                payload_dict={
                    "model": "gpt-5.4-mini",
                    "input": [
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "follow up"}],
                        }
                    ],
                    "stream": True,
                    "tools": [],
                },
                full_payload_dict={
                    "model": "gpt-5.4-mini",
                    "input": [
                        {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "follow up"}],
                        }
                    ],
                    "stream": True,
                    "tools": [],
                },
            )
        )
        assert handled is True
        assert prepared_payload.get("previous_response_id") is None
        assert reason == "no_previous_response_id_available"
        assert proxy_managed is False

    @pytest.mark.asyncio
    async def test_execute_streaming_websocket_preserves_tool_marker_through_compatibility_translation(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
        monkeypatch,
    ) -> None:
        class PassthroughCompatibilityLayer(ICompatibilityLayer):
            async def apply(self, context):
                raise NotImplementedError

            async def translate_stream_chunk(self, chunk, state):
                raw = cast(ProcessedResponse, chunk.raw)
                translated = ProcessedResponse(
                    content=raw.content,
                    usage=raw.usage,
                    metadata={},
                )
                return type(chunk)(raw=translated)

            async def cleanup_state(self, state):
                return None

            def create_state(self):
                return MagicMock()

            def detect_incompatible_tool_calls(self, tool_calls, context):
                return []

            def append_incompatible_tool_steering(
                self, payload_dict, incompatible_tool_names, context
            ):
                return payload_dict

        compatibility_state = CompatibilityState()
        sample_context.metadata = {"compatibility_state": compatibility_state}
        mock_base_connector.translation_service = TranslationService()

        async def ws_stream():
            yield ProcessedResponse(
                content={
                    "type": "response.output_item.done",
                    "output_index": 1,
                    "item": {
                        "id": "fc_ws_tool",
                        "type": "function_call",
                        "name": "shell",
                        "arguments": '{"command":["bash","-lc","git status --short"]}',
                    },
                },
                metadata={"event_type": "response.output_item.done"},
            )

        ws_client = MagicMock()
        ws_client.disconnect = AsyncMock()
        ws_client.send_response_create = MagicMock(return_value=ws_stream())

        monkeypatch.setattr(
            "src.connectors.openai_websocket_client.OpenAIWebSocketClient",
            MagicMock(return_value=ws_client),
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            compatibility_layer=PassthroughCompatibilityLayer(),
            use_websocket=True,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        chunks = [c async for c in result.content]

        assert len(chunks) == 1
        assert chunks[0].metadata.get("tool_call_emitted") is True
        assert chunks[0].metadata.get("finish_reason") == "tool_calls"

    @pytest.mark.asyncio
    async def test_execute_streaming_websocket_replays_after_previous_response_miss(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
        monkeypatch,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id = AsyncMock(
            return_value="resp_prev_missing"
        )
        streaming_payload.instructions = "Full Codex bootstrap"
        streaming_payload.tools = [
            CodexToolSchema(
                name="read_file",
                description="Read a file",
                type="function",
                parameters={"type": "object", "properties": {}},
            )
        ]

        async def gen_fail():
            if True:
                raise InvalidRequestError(
                    message="Previous response not found",
                    details={"code": "previous_response_not_found"},
                )
            yield ProcessedResponse(content={})  # pragma: no cover

        async def gen_ok():
            yield ProcessedResponse(
                content={"id": "resp_recovered_ws", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        calls = {"n": 0}

        def send_side_effect(*args: object, **kwargs: object):
            calls["n"] += 1
            if calls["n"] == 1:
                return gen_fail()
            return gen_ok()

        ws_client = MagicMock()
        ws_client.disconnect = AsyncMock()
        ws_client.send_response_create = MagicMock(side_effect=send_side_effect)

        monkeypatch.setattr(
            "src.connectors.openai_websocket_client.OpenAIWebSocketClient",
            MagicMock(return_value=ws_client),
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
            use_websocket=True,
        )

        result = await executor.execute(streaming_payload, sample_context)
        assert result.content is not None
        chunks = [c async for c in result.content]
        assert len(chunks) == 1
        assert chunks[0].metadata.get("event_type") == "response.done"
        assert ws_client.send_response_create.call_count == 2
        first_kw = ws_client.send_response_create.call_args_list[0].kwargs
        second_kw = ws_client.send_response_create.call_args_list[1].kwargs
        assert first_kw["previous_response_id"] == "resp_prev_missing"
        assert second_kw.get("previous_response_id") is None
        continuation.invalidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_streaming_websocket_previous_response_miss_logs_without_traceback(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
        monkeypatch,
        caplog,
    ) -> None:
        continuation = AsyncMock()
        continuation.resolve_previous_response_id = AsyncMock(
            return_value="resp_prev_missing"
        )

        async def gen_fail():
            if True:
                raise InvalidRequestError(
                    message="Previous response not found",
                    details={"code": "previous_response_not_found"},
                )
            yield ProcessedResponse(content={})  # pragma: no cover

        async def gen_ok():
            yield ProcessedResponse(
                content={"id": "resp_recovered_ws", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        calls = {"n": 0}

        def send_side_effect(*args: object, **kwargs: object):
            calls["n"] += 1
            if calls["n"] == 1:
                return gen_fail()
            return gen_ok()

        ws_client = MagicMock()
        ws_client.disconnect = AsyncMock()
        ws_client.send_response_create = MagicMock(side_effect=send_side_effect)

        monkeypatch.setattr(
            "src.connectors.openai_websocket_client.OpenAIWebSocketClient",
            MagicMock(return_value=ws_client),
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            continuation_coordinator=continuation,
            use_websocket=True,
        )

        with caplog.at_level(logging.WARNING):
            result = await executor.execute(streaming_payload, sample_context)
            assert result.content is not None
            async for _ in result.content:
                pass

        records = [
            record
            for record in caplog.records
            if "Handled Codex WebSocket recovery condition" in record.getMessage()
        ]
        assert records
        assert all(record.exc_info is None for record in records)

    @pytest.mark.asyncio
    async def test_execute_streaming_websocket_transport_passes_capture_context(
        self,
        mock_base_connector,
        mock_credential_manager,
        streaming_payload,
        monkeypatch,
    ) -> None:
        connector_context = ConnectorRequestContext(
            request_id="req-codex-ws",
            session_id="sess-codex-ws",
            client_host="127.0.0.1",
            extensions={"source": "test"},
        )
        # Build a fresh context with connector capture metadata to avoid mutating the shared fixture.
        from src.connectors._openai_codex_capabilities import CodexClientCapabilities
        from src.connectors.openai_codex.contracts import (
            CodexRequestContext,
            ProcessedMessage,
        )
        from src.core.domain.chat import CanonicalChatRequest, ChatMessage

        request = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="hello")],
            stream=True,
        )
        context = CodexRequestContext(
            request=request,
            processed_messages=[ProcessedMessage(role="user", content="hello")],
            effective_model="gpt-5.1-codex",
            capabilities=CodexClientCapabilities(),
            session_id="proxy-session-codex",
            metadata={
                "connector_request_context": connector_context,
                "capture_key_name": "openai-codex",
            },
        )

        async def ws_iterator():
            yield ProcessedResponse(
                content={"id": "resp_ws_terminal", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        ws_client = MagicMock()
        ws_client.disconnect = AsyncMock()
        ws_client.send_response_create = MagicMock(return_value=ws_iterator())

        monkeypatch.setattr(
            "src.connectors.openai_websocket_client.OpenAIWebSocketClient",
            MagicMock(return_value=ws_client),
        )

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            use_websocket=True,
        )

        result = await executor.execute(streaming_payload, context)
        assert result.content is not None
        async for _ in result.content:
            pass

        ws_client.send_response_create.assert_called_once()
        send_kwargs = ws_client.send_response_create.call_args.kwargs
        assert send_kwargs["context"] == connector_context
        assert send_kwargs["backend"] == "openai-codex"
        assert send_kwargs["model"] == "gpt-5.1-codex"
        assert send_kwargs["key_name"] == "openai-codex"
