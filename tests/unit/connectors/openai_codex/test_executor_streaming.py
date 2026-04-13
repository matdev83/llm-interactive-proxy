"""Streaming ResponseExecutor execution tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from src.connectors.openai_codex.executor import ResponseExecutor
from src.connectors.openai_codex.interfaces import ICompatibilityLayer
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.translators.responses.streaming import (
    reset_active_responses_stream_context,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.translation_service import TranslationService


class TestResponseExecutor:
    """Test ResponseExecutor service implementation."""

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
            None, session_id=sample_context.session_id
        )

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
            45.0, session_id=sample_context.session_id
        )

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

        async def streaming_side_effect(url, payload_dict, headers, session_id, *args):
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
