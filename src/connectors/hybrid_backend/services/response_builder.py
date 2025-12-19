"""ResponseBuilder service for constructing response envelopes.

This service extracts response building logic from HybridConnector to provide
focused, testable components for building reasoning chunks and tool-call responses.

Requirements satisfied:
- Req 2.6: ResponseBuilder extraction
- Req 3: Protocol-first design
"""

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.connectors.hybrid_backend.protocols import IReasoningMarkupProcessor
    from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
    from src.core.interfaces.response_processor_interface import ProcessedResponse

from src.connectors.hybrid_backend.protocols import (
    IReasoningMarkupProcessor,
)
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


class ResponseBuilder:
    """Service for constructing response envelopes.

    Handles building reasoning chunks, tool-call responses, and prepending
    reasoning to streaming responses.
    """

    def __init__(self, markup_processor: IReasoningMarkupProcessor) -> None:
        """Initialize ResponseBuilder.

        Args:
            markup_processor: Processor for formatting reasoning tags
        """
        self._markup_processor = markup_processor

    def _prepare_reasoning_texts(
        self, reasoning_output: str, backend: str
    ) -> tuple[str, str]:
        """Return backend-tagged reasoning and plain text representations."""
        if not reasoning_output:
            return "", ""

        tagged = self._markup_processor.format_for_model(reasoning_output, backend)
        plain = self._markup_processor.extract_plain_text(tagged) if tagged else ""

        if not plain:
            return "", ""

        return tagged, plain

    def build_reasoning_chunk(
        self,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
    ) -> ProcessedResponse | None:
        """Build a streaming chunk containing reasoning preview.

        Args:
            reasoning_output: Captured reasoning text
            reasoning_backend: Backend name for metadata
            reasoning_model: Model name for metadata

        Returns:
            ProcessedResponse chunk or None if no reasoning content
        """
        formatted, plain_reasoning = self._prepare_reasoning_texts(
            reasoning_output, reasoning_backend
        )

        if not plain_reasoning:
            return None

        reasoning_metadata: dict[str, Any] = {
            "hybrid_phase": "reasoning",
            "reasoning_backend": reasoning_backend,
            "reasoning_model": reasoning_model,
        }

        delta_payload: dict[str, Any] = {
            "role": "assistant",
            "reasoning": formatted,
            "reasoning_content": plain_reasoning,
            "content": "",
        }

        payload = {
            "id": f"hybrid-reasoning-{uuid.uuid4().hex}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": f"{reasoning_backend}:{reasoning_model}",
            "choices": [
                {
                    "index": 0,
                    "delta": delta_payload,
                    "finish_reason": None,
                    "metadata": reasoning_metadata,
                }
            ],
            "metadata": reasoning_metadata,
        }

        sse_payload = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        return ProcessedResponse(
            content=sse_payload,
            usage=None,
            metadata=reasoning_metadata,
        )

    def build_tool_call_response(
        self,
        tool_calls: list[dict[str, Any]],
        request_dict: dict[str, Any],
        backend: str,
        model: str,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """Build response for tool-call-only scenarios.

        Args:
            tool_calls: Tool calls from reasoning phase
            request_dict: Original request dictionary
            backend: Backend name for response metadata
            model: Model name for response metadata

        Returns:
            Response envelope (streaming or non-streaming) containing tool calls
        """
        stream_requested = bool(request_dict.get("stream", False))
        created_ts = int(time.time())
        model_name = f"{backend}:{model}"

        if stream_requested:
            payload = {
                "id": f"hybrid-tool-call-{uuid.uuid4().hex}",
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": tool_calls,
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
            sse_payload = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            done_payload = "data: [DONE]\n\n"

            async def tool_call_stream():
                yield ProcessedResponse(
                    content=sse_payload,
                    metadata={
                        "hybrid_phase": "reasoning",
                        "reasoning_backend": backend,
                        "reasoning_model": model,
                        "skipped_execution": True,
                    },
                )
                yield ProcessedResponse(
                    content=done_payload,
                    metadata={"is_done": True},
                )

            return StreamingResponseEnvelope(
                content=tool_call_stream(),
                media_type="text/event-stream",
            )

        response_content = {
            "id": f"hybrid-tool-call-{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": created_ts,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": tool_calls,
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }

        return ResponseEnvelope(
            content=response_content,
            metadata={
                "hybrid_phase": "reasoning",
                "reasoning_backend": backend,
                "reasoning_model": model,
                "skipped_execution": True,
            },
        )

    def prepend_reasoning_to_stream(
        self,
        response: StreamingResponseEnvelope,
        reasoning_output: str,
        reasoning_backend: str,
        reasoning_model: str,
    ) -> StreamingResponseEnvelope:
        """Prepend reasoning chunk to streaming response.

        Args:
            response: Original streaming response
            reasoning_output: Captured reasoning text
            reasoning_backend: Backend name for metadata
            reasoning_model: Model name for metadata

        Returns:
            New streaming response with reasoning chunk prepended.
            Must preserve cancel_callback from original response.
        """
        reasoning_chunk = self.build_reasoning_chunk(
            reasoning_output,
            reasoning_backend,
            reasoning_model,
        )
        if reasoning_chunk is None:
            return response

        original_stream = response.content

        async def combined_stream():
            yield reasoning_chunk
            if original_stream is None:
                return
            async for chunk in original_stream:
                yield chunk

        return StreamingResponseEnvelope(
            content=combined_stream(),
            media_type=response.media_type,
            headers=response.headers,
            cancel_callback=response.cancel_callback,
        )
