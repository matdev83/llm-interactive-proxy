"""Streaming ResponseExecutor execution tests."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from src.connectors.contracts import ConnectorRequestContext
from src.connectors.openai_codex.continuation import (
    InMemoryCodexContinuationCoordinator,
)
from src.connectors.openai_codex.contracts import CodexToolSchema
from src.connectors.openai_codex.executor import ResponseExecutor
from src.connectors.openai_codex.interfaces import ICompatibilityLayer
from src.core.common.exceptions import InvalidRequestError
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
        continuation = MagicMock()
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
        continuation = MagicMock()
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
        mock_base_connector._handle_auth_failure_rotation = AsyncMock(return_value=True)

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
        assert exc_info.value.detail["error"] == "codex_instructions_invalid"
        assert "prompt_mode" in exc_info.value.detail["suggestion"]

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
        notify_kw = (
            mock_credential_manager.notify_codex_usage_limit_unrecovered.await_args.kwargs
        )
        assert notify_kw["upstream_detail"] == detail

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
        content = cast(AsyncIterator[ProcessedResponse], result.content)
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
        content = cast(AsyncIterator[ProcessedResponse], result.content)
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
        content = cast(AsyncIterator[ProcessedResponse], result.content)
        with pytest.raises(HTTPException) as exc_info:
            async for _ in content:
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
    async def test_execute_streaming_injects_previous_response_id_from_continuation(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        continuation = MagicMock()
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

        assert captured_payloads[0]["previous_response_id"] == "resp_prev_123"
        continuation.resolve_previous_response_id.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_streaming_proxy_continuation_omits_bootstrap_fields(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        continuation = MagicMock()
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

        assert captured_payloads[0]["previous_response_id"] == "resp_prev_123"
        assert "instructions" not in captured_payloads[0]
        assert "tools" not in captured_payloads[0]

    @pytest.mark.asyncio
    async def test_execute_streaming_logs_continuation_mode_metrics(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
        caplog,
    ) -> None:
        continuation = MagicMock()
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
            if record.msg == "Submitting Codex request."
        ]
        assert matching
        assert matching[-1].continuation_mode == "continued_delta"
        assert matching[-1].input_item_count == 0
        assert matching[-1].instructions_bytes == 0
        assert matching[-1].tools_bytes == 0

    @pytest.mark.asyncio
    async def test_execute_streaming_uses_delta_suffix_for_translated_continuation(
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
        assert captured_payloads[1]["previous_response_id"] == "resp_first"
        assert "instructions" not in captured_payloads[1]
        assert "tools" not in captured_payloads[1]
        second_input = captured_payloads[1]["input"]
        assert isinstance(second_input, list)
        assert len(second_input) == 2
        full_second_size = len(
            json.dumps(second_payload.model_dump(exclude_none=True), sort_keys=True)
        )
        delta_second_size = len(json.dumps(captured_payloads[1], sort_keys=True))
        assert delta_second_size < full_second_size

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
        continuation = MagicMock()
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
    async def test_execute_streaming_invalidates_continuation_on_missing_previous_response(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        continuation = MagicMock()
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
    async def test_execute_streaming_replays_once_after_proxy_continuation_miss(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        streaming_payload,
    ) -> None:
        continuation = MagicMock()
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

        async def success_iterator():
            yield ProcessedResponse(
                content={"id": "resp_recovered_001", "output": []},
                metadata={"event_type": "response.done", "done": True},
            )

        first_handle = MagicMock()
        first_handle.headers = {}
        first_handle.cancel_callback = AsyncMock()
        first_handle.iterator = failing_iterator()

        second_handle = MagicMock()
        second_handle.headers = {}
        second_handle.cancel_callback = AsyncMock()
        second_handle.iterator = success_iterator()

        captured_payloads: list[dict[str, object]] = []

        async def handle_streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            captured_payloads.append(dict(payload_dict))
            if len(captured_payloads) == 1:
                return first_handle
            return second_handle

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
        chunks = [chunk async for chunk in result.content]

        assert len(chunks) == 1
        assert chunks[0].metadata["event_type"] == "response.done"
        assert captured_payloads[0]["previous_response_id"] == "resp_prev_missing"
        assert "instructions" not in captured_payloads[0]
        assert "tools" not in captured_payloads[0]
        assert "previous_response_id" not in captured_payloads[1]
        assert captured_payloads[1]["instructions"] == "Full Codex bootstrap"
        restored_tools = captured_payloads[1]["tools"]
        assert isinstance(restored_tools, list)
        assert restored_tools
        assert restored_tools[0]["name"] == "read_file"
        continuation.invalidate.assert_called_once()
        continuation.record_response_id.assert_called_once()

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
