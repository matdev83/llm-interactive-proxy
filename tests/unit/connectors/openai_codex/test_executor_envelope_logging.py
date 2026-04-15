"""Streaming envelope and logging behavior tests."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class TestResponseExecutor:
    """Test ResponseExecutor logging on the streaming-only execution path."""

    @pytest.mark.asyncio
    async def test_non_streaming_execute_returns_streaming_envelope_metadata(
        self, executor, non_streaming_payload, sample_context
    ):
        async def empty_iterator():
            return
            yield  # pragma: no cover

        stream_handle = MagicMock()
        stream_handle.headers = {"x-request-id": "req-1"}
        stream_handle.cancel_callback = AsyncMock()
        stream_handle.iterator = empty_iterator()
        executor._base_connector._handle_streaming_response = AsyncMock(
            return_value=stream_handle
        )

        result = await executor.execute(non_streaming_payload, sample_context)

        assert isinstance(result, StreamingResponseEnvelope)
        assert result.metadata is not None
        assert result.metadata["backend"] == "openai-codex"
        assert result.metadata["model"] == sample_context.effective_model
        assert result.metadata["session_id"] == sample_context.session_id
        async for _ in result.content:
            pass
        assert result.headers == {"x-request-id": "req-1"}

    @pytest.mark.asyncio
    async def test_info_logging_includes_correlation_fields(
        self, executor, streaming_payload, sample_context, caplog
    ):
        mock_stream_handle = MagicMock()
        mock_stream_handle.headers = {"Content-Type": "text/event-stream"}
        mock_stream_handle.cancel_callback = AsyncMock()

        async def auth_error_iterator():
            yield ProcessedResponse(
                content={
                    "error": "auth_failed",
                    "details": {"status": 401},
                }
            )

        mock_stream_handle.iterator = auth_error_iterator()

        mock_stream_handle_success = MagicMock()
        mock_stream_handle_success.headers = {}
        mock_stream_handle_success.cancel_callback = AsyncMock()

        async def success_iterator():
            yield ProcessedResponse(content=b"data: test\n\n", metadata={})

        mock_stream_handle_success.iterator = success_iterator()

        call_count = [0]

        async def handle_streaming_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_stream_handle
            return mock_stream_handle_success

        executor._base_connector._handle_streaming_response = AsyncMock(
            side_effect=handle_streaming_side_effect
        )

        caplog.set_level(logging.INFO, logger="src.connectors.openai_codex.executor")

        result = await executor.execute(streaming_payload, sample_context)
        async for _ in result.content:
            break

        info_records = [
            record
            for record in caplog.records
            if record.name == "src.connectors.openai_codex.executor"
            and record.levelno == logging.INFO
            and "authentication failure" in record.getMessage().lower()
        ]
        assert info_records
        for record in info_records:
            assert getattr(record, "session_id", None) == sample_context.session_id
            assert getattr(record, "model", None) == sample_context.effective_model
