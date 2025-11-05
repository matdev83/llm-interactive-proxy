from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_request_manager_service import BackendRequestManager


@pytest.mark.asyncio
async def test_streaming_retry_replays_full_replacement_stream() -> None:
    """Ensure streaming retries forward the complete replacement stream."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    manager = BackendRequestManager(backend_processor, response_processor)

    original_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    backend_response = ResponseEnvelope(
        content="dangerous tool response",
        metadata={
            "tool_call_swallowed": True,
            "steering_message": "Do not execute that command.",
            "swallowed_original_content": "rm -rf /",
            "swallowed_tool_calls": [
                {"function": {"name": "shell", "arguments": "{}"}}
            ],
        },
    )

    async def retry_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="safe replacement 1", metadata={})
        yield ProcessedResponse(
            content="safe replacement 2", metadata={"is_done": True}
        )

    backend_processor.process_backend_request.return_value = StreamingResponseEnvelope(
        content=retry_stream()
    )

    result = await manager._retry_after_tool_swallow(
        original_request,
        backend_response,
        "session-x",
        SimpleNamespace(),
        is_streaming=True,
    )

    assert isinstance(result, StreamingResponseEnvelope)
    chunks: list[str] = []
    async for chunk in result.content:
        chunks.append(chunk.content)

    assert chunks == ["safe replacement 1", "safe replacement 2"]
    assert backend_processor.process_backend_request.await_count == 1


@pytest.mark.asyncio
async def test_streaming_retry_skipped_when_retry_marker_present() -> None:
    """When retry marker is present, the reactor should not trigger again."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    manager = BackendRequestManager(backend_processor, response_processor)

    flagged_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="continue")],
        stream=True,
        extra_body={"_tool_call_reactor_retry": True},
    )

    async def original_stream():
        yield ProcessedResponse(
            content="proxy replacement",
            metadata={
                "tool_call_swallowed": True,
                "steering_message": "Already handled.",
            },
        )

    stream_envelope = StreamingResponseEnvelope(content=original_stream())

    result = await manager._process_streaming_response(
        stream_envelope,
        flagged_request,
        "session-y",
        SimpleNamespace(),
    )

    assert isinstance(result, StreamingResponseEnvelope)
    chunks = [chunk async for chunk in result.content]
    assert len(chunks) == 1
    assert chunks[0].metadata.get("tool_call_swallowed") is True
    assert backend_processor.process_backend_request.await_count == 0
