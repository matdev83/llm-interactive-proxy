"""Single-path parity tests for non-streaming Codex requests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from src.connectors.openai_codex.interfaces import (
    ICompatibilityLayer,
    IResponseExecutor,
)
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestResponseExecutor:
    """Verify non-stream client semantics over the streaming executor path."""

    def test_executor_implements_interface(self, executor):
        assert isinstance(executor, IResponseExecutor)

    @pytest.mark.asyncio
    async def test_execute_non_streaming_payload_returns_streaming_envelope(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        async def empty_iterator():
            return
            yield  # pragma: no cover

        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {"x-request-id": "req-123"}
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
        assert result.headers == {"x-request-id": "req-123"}
        mock_base_connector._handle_streaming_response.assert_awaited_once()
        mock_base_connector.client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_non_streaming_payload_retries_incompatible_tool_call_before_output(
        self, executor, sample_context, non_streaming_payload
    ):
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

        result = await executor.execute(non_streaming_payload, sample_context)
        chunks = [chunk async for chunk in result.content]

        assert len(chunks) == 1
        assert chunks[0].content == {"choices": [{"delta": {"content": "ok"}}]}
        assert len(captured_payloads) == 2
        assert captured_payloads[1]["instructions"] == "retry steering"
        first_handle.cancel_callback.assert_awaited()
        compatibility_layer.append_incompatible_tool_steering.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_non_streaming_payload_429_notifies_when_rotation_exhausted(
        self,
        mock_base_connector,
        mock_credential_manager,
        sample_context,
        non_streaming_payload,
    ):
        mock_credential_manager.effective_max_rate_limit_retries = AsyncMock(
            return_value=1
        )
        mock_credential_manager.notify_codex_usage_limit_unrecovered = AsyncMock()

        from src.connectors.openai_codex.executor import ResponseExecutor

        executor = ResponseExecutor(
            mock_base_connector,
            mock_credential_manager,
            max_retries=2,
            retry_backoff_seconds=(0.01,),
        )
        mock_base_connector._handle_rate_limit_rotation = AsyncMock(return_value=False)
        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=HTTPException(
                status_code=429,
                detail={
                    "error": {
                        "type": "usage_limit_reached",
                        "message": "The usage limit has been reached",
                        "plan_type": "plus",
                        "resets_in_seconds": 3600,
                    }
                },
            )
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert result.content is not None
        with pytest.raises(HTTPException) as exc_info:
            async for _ in result.content:
                pass

        assert exc_info.value.status_code == 429
        mock_credential_manager.notify_codex_usage_limit_unrecovered.assert_awaited_once()
        mock_base_connector._handle_rate_limit_rotation.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_streaming_payload_uses_prompt_cache_key_for_conversation_id(
        self, executor, mock_base_connector, sample_context, non_streaming_payload
    ):
        non_streaming_payload.prompt_cache_key = "test-conversation-key-123"
        captured_headers: list[dict[str, str]] = []

        async def empty_iterator():
            return
            yield  # pragma: no cover

        success_handle = MagicMock()
        success_handle.headers = {}
        success_handle.cancel_callback = AsyncMock()
        success_handle.iterator = empty_iterator()

        async def handle_streaming_side_effect(
            url, payload_dict, headers, session_id, *args, **kwargs
        ):
            captured_headers.append(dict(headers))
            return success_handle

        mock_base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        result = await executor.execute(non_streaming_payload, sample_context)
        async for _ in result.content:
            pass

        assert captured_headers
        assert captured_headers[0]["conversation_id"] == "test-conversation-key-123"
        assert captured_headers[0]["session_id"] == "test-conversation-key-123"
