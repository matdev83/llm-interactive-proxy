"""Reproduce empty-stream retry behavior after client disconnect.

This script simulates a streaming response that emits only `data: [DONE]`
and verifies that empty-stream retry is skipped when session cancellation
is already known.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.common.exceptions import SessionCancelledError
from src.core.domain.backend_request_manager.context_models import (
    ResponseProcessingContext,
)
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.client_termination import ClientTerminationReason
from src.core.domain.request_context import ProcessingContext, RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_request_manager.streaming_response_handler import (
    BackendStreamingResponseHandler,
)


async def _chunks(
    items: list[ProcessedResponse],
) -> AsyncIterator[ProcessedResponse]:
    for item in items:
        yield item


async def main() -> None:
    response_processor = AsyncMock()
    loop_detector_factory = MagicMock()
    quality_verifier = AsyncMock()
    tool_call_retry = AsyncMock()
    backend_processor = AsyncMock()

    done_chunk = ProcessedResponse(content=b"data: [DONE]\n\n", metadata={})
    response_processor.process_streaming_response.return_value = _chunks([done_chunk])

    loop_detector = MagicMock()
    loop_detector.process_chunk.return_value = None
    loop_detector_factory.create.return_value = loop_detector

    async def passthrough_stream(request, stream, context, **_kwargs):
        _ = request, context
        if hasattr(stream, "__await__"):
            stream = await stream
        async for chunk in stream:
            yield chunk

    quality_verifier.verify_or_passthrough = passthrough_stream

    cancellation_coordinator = MagicMock()
    cancellation_coordinator.ensure_not_cancelled.side_effect = SessionCancelledError(
        session_key=SessionKey(protocol="http", primary_id="repro-request"),
        reason=ClientTerminationReason.CLIENT_DISCONNECTED,
    )

    handler = BackendStreamingResponseHandler(
        response_processor=response_processor,
        loop_detector_factory=loop_detector_factory,
        quality_verifier_stream_verifier=quality_verifier,
        tool_call_retry_coordinator=tool_call_retry,
        backend_processor=backend_processor,
        cancellation_coordinator=cancellation_coordinator,
    )

    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hello")],
        stream=True,
    )
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        session_id="repro-session",
        request_id="repro-request",
        processing_context=ProcessingContext(),
    )
    processing_context = ResponseProcessingContext(
        session_id="repro-session",
        backend_name="openai",
        model_name="gpt-4",
        client_os="Windows",
        original_request=request,
        structured_output=None,
    )
    envelope = StreamingResponseEnvelope(content=_chunks([done_chunk]))

    result = await handler.handle(
        stream=envelope,
        request=request,
        context=context,
        processing_context=processing_context,
    )

    emitted = 0
    if result.content is not None:
        async for _ in result.content:
            emitted += 1

    print(f"emitted_chunks={emitted}")
    print(f"retry_backend_calls={backend_processor.process_backend_request.call_count}")
    if backend_processor.process_backend_request.call_count == 0:
        print("PASS: no retry after cancellation")
    else:
        print("FAIL: retry still executed after cancellation")


if __name__ == "__main__":
    asyncio.run(main())
