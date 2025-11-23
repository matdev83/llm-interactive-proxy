"""
FastAPI response adapters.

This module contains adapters for converting domain response objects
to FastAPI/Starlette response objects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi.responses import JSONResponse, Response
from starlette.responses import StreamingResponse

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.domain.chat import ChatResponse, StreamingChatResponse

# Some environments may fail mypy import resolution for local packages; silence here
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse

logger = logging.getLogger(__name__)


def _chunk_signals_done(content: Any, metadata: dict[str, Any] | None) -> bool:
    """Detect if a streaming chunk signals end-of-stream."""

    text_value: str | None = None
    if isinstance(content, bytes | bytearray):
        text_value = content.decode("utf-8", errors="ignore").strip()
    elif isinstance(content, str):
        text_value = content.strip()

    if text_value:
        if text_value == "[DONE]":
            return True
        if text_value.startswith("data: [DONE]"):
            return True

    if metadata and metadata.get("finish_reason"):
        return True

    if isinstance(content, dict):
        content_metadata = content.get("metadata")
        if isinstance(content_metadata, dict) and content_metadata.get("finish_reason"):
            return True
        choices = content.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if isinstance(choice, dict) and choice.get("finish_reason"):
                    return True

    return False


def _format_chunk_as_sse(chunk: Any) -> bytes:
    """Format a chunk as SSE (Server-Sent Events) format.

    This is the critical fix for streaming responses - dict chunks must be
    formatted as `data: {json}\\n\\n` for proper SSE format.

    Args:
        chunk: The chunk to format (dict, str, bytes, or other)

    Returns:
        Formatted chunk as bytes
    """
    if isinstance(chunk, dict):
        # Format as SSE: data: {json}\n\n
        sse_line = f"data: {json.dumps(chunk)}\n\n"
        return sse_line.encode("utf-8")
    elif isinstance(chunk, str):
        return chunk.encode()
    elif isinstance(chunk, bytes):
        return chunk
    else:
        return str(chunk).encode("utf-8")


def _normalize_content(content: Any) -> Any:
    """Normalize content into JSON-serializable structures when possible."""
    if hasattr(content, "model_dump"):
        try:
            return content.model_dump()
        except (TypeError, ValueError, AttributeError):
            logger.debug(
                "Failed to model_dump content; falling back to dict", exc_info=True
            )
            return dict(content)
    if is_dataclass(content) and not isinstance(content, type):
        return asdict(content)
    return content


def _assign_reasoning(
    payload: dict[str, Any],
    metadata: dict[str, Any],
    *,
    streaming: bool,
) -> bool:
    """Insert reasoning metadata into an OpenAI-style payload.

    Returns True when reasoning was injected into at least one choice.
    """

    reasoning_text = metadata.get("reasoning_content") or metadata.get("reasoning")
    if not reasoning_text:
        return False

    choices = payload.get("choices")
    if not isinstance(choices, list):
        return False

    assigned = False
    for choice in choices:
        if not isinstance(choice, dict):
            continue

        target_key = "delta" if (streaming or "delta" in choice) else "message"
        target = choice.get(target_key)
        if not isinstance(target, dict):
            target = {}
            choice[target_key] = target

        if target.get("reasoning_content"):
            continue

        if streaming:
            target.setdefault("role", metadata.get("role", "assistant"))
        elif metadata.get("role") and "role" not in target:
            target["role"] = metadata["role"]

        target["reasoning_content"] = reasoning_text
        target.setdefault("reasoning", metadata.get("reasoning", reasoning_text))
        assigned = True

    return assigned


def _build_streaming_payload(
    content: Any,
    metadata: dict[str, Any],
    reasoning_text: str | None,
    *,
    streaming: bool,
) -> dict[str, Any]:
    """Create an OpenAI-style payload when we can't inject into existing content."""

    chunk_id = metadata.get("id")
    if not isinstance(chunk_id, str) or not chunk_id:
        chunk_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"

    created_raw = metadata.get("created")
    if isinstance(created_raw, int):
        created = created_raw
    else:
        try:
            created = int(created_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            created = int(time.time())

    model_name = metadata.get("model") or "unknown"
    object_type = metadata.get("object")
    if not isinstance(object_type, str):
        object_type = "chat.completion.chunk" if streaming else "chat.completion"

    choice_payload: dict[str, Any] = {
        "index": metadata.get("index", 0),
        "finish_reason": metadata.get("finish_reason"),
    }

    target_key = "delta" if streaming else "message"
    target_payload: dict[str, Any] = {
        "role": metadata.get("role", "assistant"),
    }

    tool_calls = metadata.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        target_payload["tool_calls"] = tool_calls

    if reasoning_text:
        target_payload["reasoning_content"] = reasoning_text
        target_payload["reasoning"] = metadata.get("reasoning", reasoning_text)

    if isinstance(content, dict):
        target_payload.update(content)
    elif isinstance(content, str) and content.strip():
        if streaming:
            target_payload["content"] = content
        else:
            target_payload.setdefault("content", content)
    elif content not in (None, ""):
        rendered = str(content).strip()
        if rendered:
            target_payload.setdefault("content", rendered)

    choice_payload[target_key] = target_payload

    return {
        "id": chunk_id,
        "object": object_type,
        "created": created,
        "model": model_name,
        "choices": [choice_payload],
    }


def _inject_reasoning_metadata(
    content: Any,
    metadata: dict[str, Any] | None,
    *,
    streaming: bool,
) -> Any:
    """Inject reasoning metadata into OpenAI-style payloads when available."""

    normalized_content = _normalize_content(content)

    if not metadata or not isinstance(metadata, dict):
        return normalized_content

    reasoning_text = metadata.get("reasoning_content") or metadata.get("reasoning")

    if isinstance(normalized_content, dict):
        if _assign_reasoning(normalized_content, metadata, streaming=streaming):
            return normalized_content

        # If we couldn't place reasoning inside choices, surface it via metadata
        metadata_block = normalized_content.get("metadata")
        reasoning_payload = {
            "reasoning_content": reasoning_text,
            "reasoning": metadata.get("reasoning", reasoning_text),
        }
        if isinstance(metadata_block, dict):
            metadata_block.setdefault(
                "reasoning_content", reasoning_payload["reasoning_content"]
            )
            metadata_block.setdefault("reasoning", reasoning_payload["reasoning"])
        else:
            normalized_content["metadata"] = reasoning_payload
        return normalized_content

    if reasoning_text:
        return _build_streaming_payload(
            normalized_content, metadata, reasoning_text, streaming=streaming
        )

    if streaming and isinstance(normalized_content, str):
        return _build_streaming_payload(
            normalized_content, metadata, None, streaming=streaming
        )

    return normalized_content


async def _string_to_async_iterator(content: bytes) -> AsyncIterator[ProcessedResponse]:
    """Convert a bytes object to an async iterator that yields the content once."""
    yield ProcessedResponse(content=content.decode("utf-8"))


def to_fastapi_response(
    domain_response: Any, content_converter: Callable[[Any], Any] | None = None
) -> Response:
    """Convert a domain response envelope to a FastAPI response.

    Args:
        domain_response: The domain response envelope
        content_converter: Optional function to convert the content
            before creating the response

    Returns:
        A FastAPI response
    """
    envelope = _normalize_response_envelope(domain_response)
    content = _apply_content_converter(envelope.content, content_converter)
    content = _inject_reasoning_metadata(
        content, getattr(envelope, "metadata", None), streaming=False
    )
    headers = envelope.headers or {}
    status_code = envelope.status_code
    media_type = getattr(envelope, "media_type", "application/json")

    if media_type and media_type.startswith("application/json"):
        json_content = _prepare_json_content(content)

        if envelope.metadata and isinstance(json_content, dict):
            reasoning_meta = envelope.metadata.get(
                "reasoning"
            ) or envelope.metadata.get("reasoning_content")
            if reasoning_meta:
                metadata_section = json_content.setdefault("metadata", {})
                if isinstance(metadata_section, dict):
                    metadata_section.setdefault("reasoning", reasoning_meta)
                    metadata_section.setdefault("reasoning_content", reasoning_meta)

        # If the envelope has usage data, merge it into the response content.
        # This ensures that token usage from the backend is always included
        # in the final response, overriding any default/zeroed values.
        # If content appears to have been transformed, recalculate usage to match actual content.
        allow_usage_recalculation = bool(
            envelope.metadata.get("allow_usage_recalculation")
            if envelope.metadata
            else False
        )

        if envelope.usage and isinstance(json_content, dict):
            from src.core.utils.usage_recalculation import (
                extract_content_text,
                should_recalculate_usage,
            )

            # Check if we should recalculate usage based on content
            if allow_usage_recalculation and should_recalculate_usage(json_content):
                current_content = extract_content_text(json_content)
                if current_content:
                    # Recalculate completion tokens based on actual content
                    from src.core.utils.token_count import count_tokens

                    actual_completion_tokens = count_tokens(current_content)
                    original_completion_tokens = envelope.usage.get(
                        "completion_tokens", 0
                    )

                    # Only update if there's a significant difference (>5% or >10 tokens)
                    token_diff = abs(
                        original_completion_tokens - actual_completion_tokens
                    )
                    if token_diff > 10 or (
                        original_completion_tokens > 0
                        and token_diff / original_completion_tokens > 0.05
                    ):
                        prompt_tokens = envelope.usage.get("prompt_tokens", 0)
                        recalculated_usage = {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": actual_completion_tokens,
                            "total_tokens": prompt_tokens + actual_completion_tokens,
                        }
                        logger.info(
                            f"Usage recalculated: completion_tokens {original_completion_tokens} -> {actual_completion_tokens} "
                            f"(diff: {token_diff}, {token_diff/max(original_completion_tokens, 1)*100:.1f}%)"
                        )
                        json_content["usage"] = recalculated_usage
                    else:
                        json_content["usage"] = envelope.usage
                else:
                    json_content["usage"] = envelope.usage
            else:
                json_content["usage"] = envelope.usage

        # Surface middleware metadata such as reasoning streams when available.
        if envelope.metadata and isinstance(json_content, dict):
            metadata_reasoning = envelope.metadata.get(
                "reasoning"
            ) or envelope.metadata.get("reasoning_content")
            if metadata_reasoning:
                metadata_block = json_content.setdefault("metadata", {})
                if isinstance(metadata_block, dict):
                    metadata_block.setdefault("reasoning", metadata_reasoning)

        safe_content = _sanitize_json_content(json_content)
        safe_headers = _sanitize_headers(headers)
        if "content-encoding" in {k.lower(): v for k, v in safe_headers.items()}:
            import logging

            logging.getLogger(__name__).debug(
                "Content-Encoding survived sanitation: %s", safe_headers
            )
        safe_status_code = _sanitize_status_code(status_code)
        final_status_code = _handle_backend_error_status_code(
            safe_content, safe_status_code
        )
        return _create_json_response(safe_content, final_status_code, safe_headers)
    else:
        return _create_other_response(content, status_code, headers, media_type)


def _normalize_response_envelope(domain_response: Any) -> ResponseEnvelope:
    if isinstance(domain_response, ResponseEnvelope):
        return domain_response
    elif isinstance(domain_response, ChatResponse):
        return ResponseEnvelope(
            content=domain_response.model_dump(), headers=None, status_code=200
        )
    elif isinstance(domain_response, dict):
        return ResponseEnvelope(content=domain_response, headers=None, status_code=200)
    else:
        return ResponseEnvelope(content=domain_response, headers=None, status_code=200)


def _apply_content_converter(
    content: Any, converter: Callable[[Any], Any] | None
) -> Any:
    if converter:
        return converter(content)
    return content


def _prepare_json_content(content: Any) -> Any:
    if hasattr(content, "model_dump"):
        return content.model_dump()
    elif is_dataclass(content) and not isinstance(content, type):
        return asdict(content)
    return content


def _sanitize_json_content(obj: Any) -> Any:
    try:
        import asyncio

        try:
            from unittest.mock import AsyncMock

            async_mock = AsyncMock
        except ImportError:
            async_mock = None
    except ImportError:
        async_mock = None

    def _sanitize(o: Any) -> Any:
        if o is None:
            return None
        if isinstance(o, dict):
            return {k: _sanitize(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_sanitize(v) for v in o]
        if isinstance(o, tuple):
            return tuple(_sanitize(v) for v in o)
        try:
            if asyncio.iscoroutine(o):
                return str(o)
        except TypeError:
            logger.debug("Sanitize: Could not check for coroutine: %s", o)
        if async_mock is not None:
            try:
                if isinstance(o, async_mock):
                    return str(o)
            except TypeError:
                logger.debug("Sanitize: Could not check for async_mock: %s", o)
        try:
            json.dumps(o)
            return o
        except TypeError:
            return str(o)

    return _sanitize(obj)


def _sanitize_headers(headers: Any) -> dict[str, Any]:
    safe_headers = {}
    if headers is not None:
        if hasattr(headers, "items") and not callable(headers):
            try:
                safe_headers = dict(headers)
            except (TypeError, ValueError):
                safe_headers = {}
        elif hasattr(headers, "_mock_name") or hasattr(headers, "_execute_mock_call"):
            safe_headers = {}
    # Allow headers that are useful for clients:
    # - x-* (custom headers)
    # - access-control-* (CORS)
    # - anthropic-* (Anthropic-specific headers including usage/rate limits)
    # - openai-* (OpenAI-specific headers)
    # - zenmux-* (ZenMux-specific headers)
    allowed_prefixes = ("x-", "access-control-", "anthropic-", "openai-", "zenmux-")
    hop_by_hop = {
        "content-encoding",
        "transfer-encoding",
        "content-length",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "upgrade",
    }
    filtered: dict[str, Any] = {}
    for key, value in safe_headers.items():
        lowercase = key.lower()
        if lowercase in hop_by_hop:
            continue
        if lowercase.startswith(allowed_prefixes):
            filtered[key] = value
    return filtered


def _sanitize_status_code(status_code: Any) -> int:
    safe_status_code = 200
    if status_code is not None:
        if hasattr(status_code, "_mock_name") or hasattr(
            status_code, "_execute_mock_call"
        ):
            safe_status_code = 200
        else:
            try:
                safe_status_code = int(status_code)
            except (TypeError, ValueError):
                safe_status_code = 200
    return safe_status_code


def _handle_backend_error_status_code(content: Any, status_code: int) -> int:
    # Preserve original status code; specific error mappings are handled upstream
    return status_code


def _create_json_response(
    content: Any, status_code: int, headers: dict[str, Any]
) -> JSONResponse:
    # Allow provider-specific headers for usage tracking and rate limiting
    allowed_prefixes = ("x-", "access-control-", "anthropic-", "openai-", "zenmux-")
    filtered_headers = {
        k: v
        for k, v in (headers or {}).items()
        if k.lower().startswith(allowed_prefixes)
    }

    response = JSONResponse(
        content=content,
        status_code=status_code,
        media_type="application/json",
    )
    for key, value in filtered_headers.items():
        response.headers[key] = value
    return response


def _create_other_response(
    content: Any, status_code: int, headers: dict[str, Any], media_type: str
) -> Response:
    content_str = content
    if isinstance(content, dict | list | tuple):
        try:
            content_str = json.dumps(content)
        except (TypeError, ValueError):
            content_str = str(content)

    return Response(
        content=content_str,
        status_code=status_code,
        headers=headers,
        media_type=media_type,
    )


def to_fastapi_streaming_response(
    domain_response: StreamingResponseEnvelope,
) -> StreamingResponse:
    """Convert a domain streaming response envelope to a FastAPI streaming response.

    This function uses the new streaming pipeline with SSEAssembler to convert
    internal StreamingContent to SSE format. It ensures proper event loop yielding
    and maintains async path purity.

    Args:
        domain_response: The domain streaming response envelope

    Returns:
        A FastAPI streaming response
    """
    from src.core.ports.sse_assembler import SSEAssembler
    from src.core.ports.streaming_contracts import StreamingContent

    async def _streaming_adapter(
        it: AsyncIterator[Any] | Iterable[Any] | None,
    ) -> AsyncIterator[bytes]:
        """Adapt the input stream to use the new streaming pipeline.

        This adapter converts ProcessedResponse chunks to StreamingContent,
        applies reasoning metadata injection, and uses SSEAssembler for
        proper SSE formatting.
        """
        if it is None:
            return

        # Create SSE assembler for output formatting
        assembler = SSEAssembler()

        async def _convert_to_streaming_content() -> AsyncIterator[StreamingContent]:
            """Convert input chunks to StreamingContent format."""
            try:
                chunk_count = 0
                async for chunk in it:  # type: ignore
                    chunk_count += 1
                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(
                            TRACE_LEVEL, "[STREAMING] Processing chunk #%s", chunk_count
                        )

                    # Extract content and metadata from ProcessedResponse
                    if isinstance(chunk, ProcessedResponse):
                        metadata = chunk.metadata or {}
                        content = chunk.content
                    else:
                        metadata = {}
                        content = chunk

                    # Check if content is already SSE formatted (legacy path)
                    if isinstance(content, str) and content.strip().startswith(
                        "data: "
                    ):
                        # For legacy SSE-formatted content, pass through as-is
                        # by wrapping in StreamingContent
                        is_done = _chunk_signals_done(content, metadata)
                        yield StreamingContent(
                            content=content, metadata=metadata, is_done=is_done
                        )
                        if is_done:
                            break
                        continue

                    # Inject reasoning metadata for OpenAI-style payloads
                    enriched = _inject_reasoning_metadata(
                        content, metadata, streaming=True
                    )

                    # Check if this chunk signals completion
                    is_done = _chunk_signals_done(enriched, metadata)

                    # Create StreamingContent directly
                    streaming_content = StreamingContent(
                        content=enriched,
                        metadata=metadata,
                        is_done=is_done,
                        stream_id=metadata.get("stream_id"),
                    )

                    yield streaming_content

                    # Yield control to event loop (Requirement 9.4)
                    await asyncio.sleep(0)

                    if is_done:
                        break

                if logger.isEnabledFor(TRACE_LEVEL):
                    logger.log(
                        TRACE_LEVEL,
                        "[STREAMING] Stream completed with %s chunks",
                        chunk_count,
                    )

            except Exception as e:
                # Log unexpected errors during streaming
                logger.error(
                    "Error during streaming content conversion: %s", e, exc_info=True
                )
                # Yield an error chunk
                yield StreamingContent(
                    content="",
                    metadata={"error": str(e), "finish_reason": "error"},
                    is_done=True,
                )

        # Convert to StreamingContent and assemble as SSE
        streaming_content_iter = _convert_to_streaming_content()
        sse_bytes_iter = assembler.assemble_stream(streaming_content_iter, format="sse")

        # Yield SSE-formatted bytes with event loop yielding
        async for sse_chunk in sse_bytes_iter:
            yield sse_chunk
            # Ensure event loop yielding for responsiveness (Requirement 9.4)
            await asyncio.sleep(0)

    content_iter = domain_response.content
    if content_iter is None:
        # Create empty iterator if content is None
        async def _empty_streamer() -> AsyncIterator[bytes]:
            return
            yield  # type: ignore  # pragma: no cover

        return StreamingResponse(
            content=_empty_streamer(),
            media_type=getattr(domain_response, "media_type", "text/event-stream"),
            headers=domain_response.headers or {},
        )

    return StreamingResponse(
        content=_streaming_adapter(content_iter),
        media_type=getattr(domain_response, "media_type", "text/event-stream"),
        headers=domain_response.headers or {},
    )


def domain_response_to_fastapi(
    domain_response: Any, content_converter: Callable[[Any], Any] | None = None
) -> Response | StreamingResponse:
    """Convert any domain response to a FastAPI response.

    This function detects the type of domain response and calls the appropriate
    adapter function.

    Args:
        domain_response: The domain response envelope (streaming or non-streaming)
        content_converter: Optional function to convert the content for non-streaming
            responses before creating the response

    Returns:
        A FastAPI response (streaming or non-streaming)
    """
    # Detect streaming envelope by type name or class
    if (
        isinstance(domain_response, StreamingResponseEnvelope)
        or domain_response.__class__.__name__ == "StreamingResponseEnvelope"
    ):
        return to_fastapi_streaming_response(domain_response)

    # If it's a StreamingChatResponse, convert to StreamingResponseEnvelope
    if isinstance(domain_response, StreamingChatResponse):
        # Create a proper StreamingResponseEnvelope - StreamingChatResponse doesn't have
        # headers, status_code, or media_type attributes
        content_bytes = (
            str(domain_response.content).encode() if domain_response.content else b""
        )
        content_iterator = _string_to_async_iterator(content_bytes)

        return to_fastapi_streaming_response(
            StreamingResponseEnvelope(
                content=content_iterator, media_type="text/event-stream", headers={}
            )
        )

    return to_fastapi_response(domain_response, content_converter)
