"""
Response accumulation utilities for Gemini Code Assist streaming responses.

This module extracts the logic for accumulating streaming responses
into non-streaming ResponseEnvelope objects.
"""

import json
import logging
import time
import uuid
from typing import Any

from fastapi import HTTPException

from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse

logger = logging.getLogger(__name__)


class StreamingResponseAccumulator:
    """Accumulates streaming responses into non-streaming ResponseEnvelopes.

    This class handles the conversion of streaming response chunks into
    a complete response when non-streaming mode is requested but the
    backend only supports streaming (e.g., Gemini Code Assist API).
    """

    def __init__(self, backend_type: str = "gemini"):
        self.backend_type = backend_type

    async def accumulate(
        self,
        streaming_response: StreamingResponseEnvelope,
    ) -> ResponseEnvelope:
        """Accumulate a streaming response into a non-streaming ResponseEnvelope.

        Args:
            streaming_response: The streaming response envelope to accumulate

        Returns:
            A ResponseEnvelope containing the accumulated content
        """
        accumulated_content_parts: list[str] = []
        accumulated_tool_calls: list[dict[str, Any]] = []
        finish_reason: str | None = None
        usage_data: dict[str, int] | None = None
        accumulated_reasoning_parts: list[str] = []
        error_data: dict[str, Any] | None = None

        try:
            if streaming_response.content is None:
                return self._build_empty_response()

            async for chunk in streaming_response.content:
                result = self._process_chunk(
                    chunk,
                    accumulated_content_parts,
                    accumulated_tool_calls,
                    finish_reason,
                    usage_data,
                    accumulated_reasoning_parts,
                    error_data,
                )
                (
                    accumulated_content_parts,
                    accumulated_tool_calls,
                    finish_reason,
                    usage_data,
                    accumulated_reasoning_parts,
                    error_data,
                ) = result

        except HTTPException as exc:
            detail = exc.detail
            if isinstance(detail, dict):
                error_data = dict(detail)
                error_data.setdefault("code", exc.status_code)
                if "message" not in error_data:
                    if isinstance(error_data.get("error"), str):
                        error_data["message"] = error_data["error"]
                    else:
                        error_data["message"] = str(detail)
            else:
                error_data = {
                    "message": str(detail),
                    "type": "backend_error",
                    "code": exc.status_code,
                }

            return self._build_error_response(
                error_data, streaming_response.headers or {}
            )

        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Error accumulating streaming response: %s", e, exc_info=True
                )
            if error_data is None:
                error_data = {
                    "message": f"Error processing response: {e}",
                    "type": "internal_error",
                    "code": 500,
                }

        # Handle error responses
        if error_data:
            return self._build_error_response(
                error_data, streaming_response.headers or {}
            )

        # Build successful response
        return self._build_success_response(
            "".join(accumulated_content_parts),
            accumulated_tool_calls,
            finish_reason,
            usage_data,
            "".join(accumulated_reasoning_parts),
            streaming_response.headers or {},
            streaming_response.status_code or 200,
        )

    def _process_chunk(
        self,
        chunk: Any,
        accumulated_content_parts: list[str],
        accumulated_tool_calls: list[dict[str, Any]],
        finish_reason: str | None,
        usage_data: dict[str, int] | None,
        accumulated_reasoning_parts: list[str],
        error_data: dict[str, Any] | None,
    ) -> tuple[
        list[str],
        list[dict[str, Any]],
        str | None,
        dict[str, int] | None,
        list[str],
        dict[str, Any] | None,
    ]:
        """Process a single chunk and update accumulated state."""
        # Handle ProcessedResponse objects
        if hasattr(chunk, "content"):
            chunk_content = chunk.content
        else:
            chunk_content = chunk

        # Handle dict content directly
        if isinstance(chunk_content, dict):
            return self._process_openai_chunk(
                chunk_content,
                accumulated_content_parts,
                accumulated_tool_calls,
                finish_reason,
                usage_data,
                accumulated_reasoning_parts,
                error_data,
            )

        # Parse SSE data format (for raw SSE streams)
        if isinstance(chunk_content, bytes):
            chunk_content = chunk_content.decode("utf-8", errors="ignore")

        if not isinstance(chunk_content, str):
            return (
                accumulated_content_parts,
                accumulated_tool_calls,
                finish_reason,
                usage_data,
                accumulated_reasoning_parts,
                error_data,
            )

        # Handle SSE data lines
        for line in chunk_content.split("\n"):
            line = line.strip()
            if not line.startswith("data:"):
                continue

            data_str = line[5:].strip()
            if data_str == "[DONE]":
                continue

            try:
                data = json.loads(data_str)
                (
                    accumulated_content_parts,
                    accumulated_tool_calls,
                    finish_reason,
                    usage_data,
                    accumulated_reasoning_parts,
                    error_data,
                ) = self._process_openai_chunk(
                    data,
                    accumulated_content_parts,
                    accumulated_tool_calls,
                    finish_reason,
                    usage_data,
                    accumulated_reasoning_parts,
                    error_data,
                )
            except json.JSONDecodeError:
                continue

        return (
            accumulated_content_parts,
            accumulated_tool_calls,
            finish_reason,
            usage_data,
            accumulated_reasoning_parts,
            error_data,
        )

    def _process_openai_chunk(
        self,
        data: dict[str, Any],
        accumulated_content_parts: list[str],
        accumulated_tool_calls: list[dict[str, Any]],
        finish_reason: str | None,
        usage_data: dict[str, int] | None,
        accumulated_reasoning_parts: list[str],
        error_data: dict[str, Any] | None,
    ) -> tuple[
        list[str],
        list[dict[str, Any]],
        str | None,
        dict[str, int] | None,
        list[str],
        dict[str, Any] | None,
    ]:
        """Process an OpenAI-style chunk and accumulate content."""
        # Check for error in the chunk
        if data.get("error"):
            error_data = data.get("error")
            choices = data.get("choices", [])
            if choices and choices[0].get("finish_reason"):
                finish_reason = choices[0]["finish_reason"]
            return (
                accumulated_content_parts,
                accumulated_tool_calls,
                finish_reason,
                usage_data,
                accumulated_reasoning_parts,
                error_data,
            )

        choices = data.get("choices", [])
        if choices:
            choice = choices[0]
            # Handle both streaming delta and non-streaming message formats
            delta = choice.get("delta", {}) or choice.get("message", {})

            # Accumulate text content
            content_piece = delta.get("content")
            if content_piece:
                accumulated_content_parts.append(content_piece)

            # Accumulate reasoning content (for thinking models)
            reasoning_piece = delta.get("reasoning_content") or delta.get("reasoning")
            if reasoning_piece:
                accumulated_reasoning_parts.append(reasoning_piece)

            # Accumulate tool calls
            if "tool_calls" in delta:
                accumulated_tool_calls = self._accumulate_tool_calls(
                    delta["tool_calls"], accumulated_tool_calls
                )

            # Capture finish reason
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

        # Capture usage data
        if data.get("usage"):
            usage_data = data["usage"]

        return (
            accumulated_content_parts,
            accumulated_tool_calls,
            finish_reason,
            usage_data,
            accumulated_reasoning_parts,
            error_data,
        )

    def _accumulate_tool_calls(
        self,
        tool_calls_delta: list[dict[str, Any]],
        accumulated_tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Accumulate tool calls from streaming deltas."""
        for tc in tool_calls_delta:
            tc_index = tc.get("index", len(accumulated_tool_calls))
            while len(accumulated_tool_calls) <= tc_index:
                accumulated_tool_calls.append(
                    {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                )
            if tc.get("id"):
                accumulated_tool_calls[tc_index]["id"] = tc["id"]
            if "function" in tc:
                fn = tc["function"]
                if fn.get("name"):
                    accumulated_tool_calls[tc_index]["function"]["name"] = fn["name"]
                if "arguments" in fn:
                    accumulated_tool_calls[tc_index]["function"]["arguments"] += fn[
                        "arguments"
                    ]
        return accumulated_tool_calls

    def _build_empty_response(self) -> ResponseEnvelope:
        """Build an empty response for empty streams."""
        return ResponseEnvelope(
            content={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "stop",
                    }
                ]
            },
            headers={},
            status_code=200,
        )

    def _build_error_response(
        self, error_data: dict[str, Any], headers: dict[str, str]
    ) -> ResponseEnvelope:
        """Build an error response envelope."""
        error_status_code = error_data.get("code", 500)
        if isinstance(error_status_code, str):
            try:
                error_status_code = int(error_status_code)
            except ValueError:
                error_status_code = 500

        error_response: dict[str, Any] = {
            "id": f"chatcmpl-error-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.backend_type,
            "choices": [],
            "error": error_data,
        }
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Returning error response for non-streaming request: %s",
                error_data.get("message", "Unknown error"),
            )
        return ResponseEnvelope(
            content=error_response,
            headers=headers,
            status_code=error_status_code,
            usage=None,
        )

    def _build_success_response(
        self,
        accumulated_content: str,
        accumulated_tool_calls: list[dict[str, Any]],
        finish_reason: str | None,
        usage_data: dict[str, int] | None,
        accumulated_reasoning: str,
        headers: dict[str, str],
        status_code: int,
    ) -> ResponseEnvelope:
        """Build a successful response envelope."""
        message_content: dict[str, Any] = {
            "role": "assistant",
            "content": accumulated_content if accumulated_content else None,
        }

        # Add reasoning content if present
        if accumulated_reasoning:
            message_content["reasoning_content"] = accumulated_reasoning

        response_content: dict[str, Any] = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.backend_type,
            "choices": [
                {
                    "index": 0,
                    "message": message_content,
                    "finish_reason": finish_reason or "stop",
                }
            ],
        }

        # Add tool calls if present
        if accumulated_tool_calls:
            response_content["choices"][0]["message"][
                "tool_calls"
            ] = accumulated_tool_calls
            if not finish_reason:
                response_content["choices"][0]["finish_reason"] = "tool_calls"

        # Add usage data if available
        if usage_data:
            response_content["usage"] = usage_data

        from src.core.domain.usage_summary import UsageSummary

        return ResponseEnvelope(
            content=response_content,
            headers=headers,
            status_code=status_code,
            usage=UsageSummary.from_dict(usage_data) if usage_data else None,
        )


def response_envelope_to_stream_chunk(
    response: ResponseEnvelope, model: str, backend_type: str = "gemini"
) -> ProcessedResponse:
    """Convert a non-streaming response into a single streaming chunk.

    Args:
        response: The ResponseEnvelope to convert
        model: The model name for the chunk
        backend_type: The backend type for metadata

    Returns:
        A ProcessedResponse containing the streaming chunk
    """

    created_ts = int(time.time())
    chunk_id = f"chatcmpl-fallback-{created_ts}"

    text_content: str
    if isinstance(response.content, str):
        text_content = response.content
    elif isinstance(response.content, dict):
        text_content = (
            response.content.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        if not text_content:
            text_content = json.dumps(response.content)
    else:
        text_content = str(response.content or "")

    payload = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created_ts,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"content": text_content},
                "finish_reason": "stop",
            }
        ],
    }

    from pydantic.types import JsonValue

    metadata: dict[str, JsonValue] = {
        "finish_reason": "stop",
        "id": chunk_id,
        "model": model,
        "created": created_ts,
        "graceful_degradation": True,
    }
    if response.usage:
        metadata["usage"] = response.usage.to_legacy_dict()

    from typing import cast

    from pydantic.types import JsonValue

    # Cast payload to ProcessedChunkContent (dict[str, JsonValue] is valid)
    payload_content: dict[str, JsonValue] = cast(dict[str, JsonValue], payload)
    return ProcessedResponse(
        content=payload_content, metadata=metadata, usage=response.usage
    )
