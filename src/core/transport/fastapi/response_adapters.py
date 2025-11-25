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
from src.core.domain.request_context import RequestContext

# Some environments may fail mypy import resolution for local packages; silence here
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.streaming.stream_context_registry import (
    get_global_streaming_context_registry,
)

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
        if text_value == '["DONE"]':
            return True
        if text_value.startswith("data: [DONE]"):
            return True
        if text_value.startswith('data: ["DONE"]'):
            return True

    normalized_event: str | None = None
    if metadata:
        event_type = metadata.get("event_type")
        if isinstance(event_type, str):
            normalized_event = event_type.strip().lower()

    finish_reason_present = bool(metadata and metadata.get("finish_reason"))
    if finish_reason_present and (
        not normalized_event or normalized_event in {"message_stop", "message_done"}
    ):
        # Only treat as done when there is no payload content/delta
        if content is None or content == "":
            return True
        if isinstance(content, dict):
            choices = content.get("choices") or []
            if choices:
                delta = choices[0].get("delta") if isinstance(choices[0], dict) else {}
                if not delta or all(
                    not delta.get(key)
                    for key in (
                        "content",
                        "tool_calls",
                        "reasoning_content",
                        "reasoning",
                    )
                ):
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
    domain_response: Any,
    content_converter: Callable[[Any], Any] | None = None,
    *,
    wire_capture: IWireCapture | None = None,
    context: RequestContext | None = None,
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
        _maybe_capture_outbound_response(
            wire_capture=wire_capture,
            context=context,
            envelope=envelope,
            payload=safe_content,
        )
        return _create_json_response(safe_content, final_status_code, safe_headers)
    else:
        _maybe_capture_outbound_response(
            wire_capture=wire_capture,
            context=context,
            envelope=envelope,
            payload=content,
        )
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


def _infer_capture_fields(
    envelope: Any, context: RequestContext | None
) -> tuple[str, str, str | None, str | None]:
    """Extract backend/model/key and session identifiers for capture."""
    backend = "proxy"
    model = "unknown"
    key_name: str | None = None
    session_id: str | None = None

    metadata = getattr(envelope, "metadata", None)
    if isinstance(metadata, dict):
        backend = str(metadata.get("backend", backend) or backend)
        model = str(metadata.get("model", model) or model)
        key_name_candidate = metadata.get("key_name")
        if isinstance(key_name_candidate, str) and key_name_candidate.strip():
            key_name = key_name_candidate
        session_candidate = metadata.get("session_id") or metadata.get("stream_id")
        if isinstance(session_candidate, str) and session_candidate.strip():
            session_id = session_candidate

    if context is not None:
        ctx_session = getattr(context, "session_id", None)
        if isinstance(ctx_session, str) and ctx_session.strip():
            session_id = ctx_session

    return backend, model, key_name, session_id


def _resolve_capture_session_id(
    session_id: str | None, context: RequestContext | None
) -> str | None:
    """Resolve session identifier with fallbacks to request_id."""
    if session_id and str(session_id).strip():
        return str(session_id)
    if context is None:
        return None
    request_id = getattr(context, "request_id", None)
    if isinstance(request_id, str) and request_id.strip():
        return request_id
    return None


def _maybe_capture_outbound_response(
    *,
    wire_capture: IWireCapture | None,
    context: RequestContext | None,
    envelope: Any,
    payload: Any,
) -> None:
    """Best-effort capture of outbound non-streaming responses."""
    if wire_capture is None or not wire_capture.enabled():
        return
    backend, model, key_name, session_id = _infer_capture_fields(envelope, context)
    session_value = _resolve_capture_session_id(session_id, context)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    task = loop.create_task(
        wire_capture.capture_outbound_response(
            context=context,
            session_id=session_value,
            backend=backend,
            model=model,
            key_name=key_name,
            response_content=payload,
        )
    )
    # This ensures the task is stored and prevents it from being garbage-collected
    # while also handling potential exceptions to avoid "not awaited" warnings.
    task.add_done_callback(lambda t: t.exception())


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
    *,
    wire_capture: IWireCapture | None = None,
    context: RequestContext | None = None,
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

    capture_backend, capture_model, capture_key_name, inferred_session_id = (
        _infer_capture_fields(domain_response, context)
    )
    capture_session_id = _resolve_capture_session_id(inferred_session_id, context)

    async def _streaming_adapter(
        it: AsyncIterator[Any] | Iterable[Any] | None,
    ) -> AsyncIterator[bytes]:
        """Adapt the input stream to use the new streaming pipeline.

        This adapter converts ProcessedResponse chunks to StreamingContent when needed
        and uses SSEAssembler for proper formatting. When the upstream already emits
        SSE-formatted bytes (new pipeline), it passes them through without re-wrapping.
        """
        if it is None:
            return

        assembler = SSEAssembler()
        context_registry = get_global_streaming_context_registry()

        async def _ensure_async_iterator(
            source: AsyncIterator[Any] | Iterable[Any],
        ) -> AsyncIterator[Any]:
            if hasattr(source, "__aiter__"):
                async for item in source:  # type: ignore[async-for]
                    yield item
            else:
                for item in source:  # type: ignore[union-attr]
                    yield item

        def _extract_payload_and_metadata(
            chunk: Any,
        ) -> tuple[Any, dict[str, Any]]:
            if isinstance(chunk, ProcessedResponse):
                return chunk.content, chunk.metadata or {}
            return chunk, {}

        def _merge_metadata_from_payload(
            payload: Any, metadata: dict[str, Any] | None
        ) -> dict[str, Any]:
            merged: dict[str, Any] = dict(metadata) if metadata else {}

            if isinstance(payload, dict):
                if "finish_reason" not in merged:
                    finish_reason = payload.get("finish_reason")
                    if not finish_reason:
                        choices = payload.get("choices")
                        if isinstance(choices, list):
                            for choice in choices:
                                if isinstance(choice, dict):
                                    finish_reason = choice.get("finish_reason")
                                    if finish_reason:
                                        break
                    if finish_reason:
                        merged["finish_reason"] = finish_reason

                if "error" not in merged and isinstance(payload.get("error"), dict):
                    merged["error"] = payload["error"]

                for key in ("id", "model", "created"):
                    if key not in merged and key in payload:
                        merged[key] = payload[key]

            return merged

        def _decode_sse_payload(
            payload: Any,
        ) -> tuple[Any, dict[str, Any], bool]:
            """Decode SSE-formatted payloads into structured content."""
            text_payload: str | None = None
            if isinstance(payload, bytes | bytearray):
                try:
                    text_payload = payload.decode("utf-8")
                except UnicodeDecodeError:
                    return payload, {}, False
            elif isinstance(payload, str):
                text_payload = payload
            else:
                return payload, {}, False

            stripped = text_payload.strip()
            if "data:" not in stripped:
                return payload, {}, False

            data_lines: list[str] = []
            for line in stripped.splitlines():
                if line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())

            if not data_lines:
                return payload, {}, False

            data_body = "\n".join(data_lines).strip()
            if data_body in ("[DONE]", '["DONE"]'):
                return "", {"finish_reason": "stop"}, True

            try:
                decoded = json.loads(data_body)
            except json.JSONDecodeError:
                return data_body, {}, False

            metadata_hint: dict[str, Any] = {}
            finish_reason = decoded.get("finish_reason")
            if finish_reason:
                metadata_hint["finish_reason"] = finish_reason
            event_type = decoded.get("type")
            if isinstance(event_type, str):
                metadata_hint["event_type"] = event_type.strip().lower()

            return decoded, metadata_hint, False

        def _extract_delta_from_payload(payload: Any) -> dict[str, Any] | None:
            if not isinstance(payload, dict):
                return None
            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices:
                return None
            first_choice = choices[0]
            if not isinstance(first_choice, dict):
                return None
            delta = first_choice.get("delta")
            if isinstance(delta, dict):
                return delta
            return None

        def _resolve_stream_key(metadata: dict[str, Any]) -> str:
            # Priority: stream_id (from StreamNormalizer) > session_id (consistent per request) > id (per-chunk, NOT suitable for buffering)
            # IMPORTANT: Do NOT use "id" as it's different for each chunk (e.g., chatcmpl-xxx)
            # and will break tool call buffering across chunks
            for candidate_key in ("stream_id", "session_id"):
                value = metadata.get(candidate_key)
                if isinstance(value, str) and value:
                    return value
            return "anonymous-stream"

        BUFFERED_TOOL_TAGS: tuple[str, ...] = (
            # Command execution tools
            "execute_command",
            # File editing tools
            "patch_file",
            "apply_diff",
            "write_to_file",
            "insert_content",
            "delete_file",
            # File reading tools
            "read_file",
            "list_files",
            "list_code_definition_names",
            "search_files",
            # MCP tools
            "use_mcp_tool",
            "access_mcp_resource",
            # Conversation control tools (CRITICAL: prevents leakage like "What can I help you with today?</")
            "ask_followup_question",
            "attempt_completion",
            "switch_mode",
            "new_task",
            "update_todo_list",
            # Browser tools
            "browser_action",
            # Other tools
            "fetch_instructions",
        )

        def _split_tag_segments(buffer: str, tag_name: str) -> tuple[str, str]:
            if not buffer:
                return "", ""

            parts: list[str] = []
            idx = 0
            length = len(buffer)
            pending_tail = ""
            open_tag = f"<{tag_name}"
            close_tag = f"</{tag_name}>"

            while idx < length:
                start = buffer.find(open_tag, idx)
                if start == -1:
                    parts.append(buffer[idx:])
                    pending_tail = ""
                    break

                if start > idx:
                    parts.append(buffer[idx:start])

                end = buffer.find(close_tag, start)
                if end == -1:
                    pending_tail = buffer[start:]
                    break

                end += len(close_tag)
                parts.append(buffer[start:end])
                idx = end

                if idx >= length:
                    pending_tail = ""
                    break

            return "".join(parts), pending_tail

        def _get_target_tags(stream_key: str) -> tuple[str, ...]:
            """Get target tool tags, preferring dynamic ones from registry."""
            # Try to get dynamic tools from registry
            try:
                buffer_state = context_registry.get_tool_call_buffer(stream_key)
                if buffer_state.allowed_tools:
                    return tuple(buffer_state.allowed_tools)
            except Exception:
                pass
            return BUFFERED_TOOL_TAGS

        def _apply_tag_buffer(stream_key: str, tag_name: str, text_value: str) -> str:
            buffer_key = f"tool-block:{tag_name}"
            buffer = context_registry.get_fragment(stream_key, buffer_key)
            combined = buffer + text_value
            emit_text, pending_tail = _split_tag_segments(combined, tag_name)
            if pending_tail:
                context_registry.set_fragment(stream_key, buffer_key, pending_tail)
            else:
                context_registry.clear_fragment(stream_key, buffer_key)
            return emit_text

        def _sanitize_multiline_tool_blocks(stream_key: str, payload: Any) -> None:
            delta = _extract_delta_from_payload(payload)
            if not delta:
                return

            text_value = delta.get("content")
            if not isinstance(text_value, str) or not text_value:
                return

            updated_text = text_value
            target_tags = _get_target_tags(stream_key)
            for tag in target_tags:
                updated_text = _apply_tag_buffer(stream_key, tag, updated_text)

            if updated_text != text_value:
                delta["content"] = updated_text

        def _flush_pending_tool_blocks(stream_key: str, payload: Any) -> None:
            pending_fragments: list[str] = []
            target_tags = _get_target_tags(stream_key)
            for tag in target_tags:
                buffer_key = f"tool-block:{tag}"
                fragment = context_registry.get_fragment(stream_key, buffer_key)
                if fragment:
                    pending_fragments.append(fragment)
                    context_registry.clear_fragment(stream_key, buffer_key)

            if not pending_fragments:
                return

            delta = _extract_delta_from_payload(payload)
            if not delta:
                return

            existing = delta.get("content")
            if isinstance(existing, str):
                delta["content"] = existing + "".join(pending_fragments)
            elif existing is None:
                delta["content"] = "".join(pending_fragments)
            else:
                delta["content"] = f"{existing}{''.join(pending_fragments)}"

        async def _convert_to_streaming_content(
            source: AsyncIterator[Any],
        ) -> AsyncIterator[StreamingContent]:
            try:
                chunk_count = 0
                async for chunk in source:
                    chunk_count += 1
                    if logger.isEnabledFor(TRACE_LEVEL):
                        logger.log(
                            TRACE_LEVEL, "[STREAMING] Processing chunk #%s", chunk_count
                        )

                    payload, metadata = _extract_payload_and_metadata(chunk)
                    decoded_payload, sse_metadata, forced_done = _decode_sse_payload(
                        payload
                    )

                    if sse_metadata:
                        updated_metadata = dict(metadata) if metadata else {}
                        updated_metadata.update(sse_metadata)
                        metadata = updated_metadata

                    metadata = _merge_metadata_from_payload(decoded_payload, metadata)

                    stream_key = _resolve_stream_key(metadata)
                    _sanitize_multiline_tool_blocks(stream_key, decoded_payload)

                    # Inject reasoning metadata for OpenAI-style payloads
                    enriched = _inject_reasoning_metadata(
                        decoded_payload, metadata, streaming=True
                    )

                    # Check if this chunk signals completion
                    is_done = forced_done or _chunk_signals_done(enriched, metadata)

                    if is_done:
                        _flush_pending_tool_blocks(stream_key, decoded_payload)

                    streaming_content = StreamingContent(
                        content=enriched,
                        metadata=metadata,
                        is_done=is_done,
                        stream_id=metadata.get("stream_id"),
                    )

                    yield streaming_content

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
                logger.error(
                    "Error during streaming content conversion: %s", e, exc_info=True
                )
                yield StreamingContent(
                    content="",
                    metadata={"error": str(e), "finish_reason": "error"},
                    is_done=True,
                )

        iterator = _ensure_async_iterator(it)
        streaming_content_iter = _convert_to_streaming_content(iterator)
        sse_bytes_iter = assembler.assemble_stream(streaming_content_iter, format="sse")

        if wire_capture and wire_capture.enabled():
            sse_bytes_iter = wire_capture.wrap_outbound_stream(
                context=context,
                session_id=capture_session_id,
                backend=capture_backend,
                model=capture_model,
                key_name=capture_key_name,
                stream=sse_bytes_iter,
            )

        async for sse_chunk in sse_bytes_iter:
            yield sse_chunk
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
    domain_response: Any,
    content_converter: Callable[[Any], Any] | None = None,
    *,
    wire_capture: IWireCapture | None = None,
    context: RequestContext | None = None,
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
        return to_fastapi_streaming_response(
            domain_response, wire_capture=wire_capture, context=context
        )

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
            ),
            wire_capture=wire_capture,
            context=context,
        )

    return to_fastapi_response(
        domain_response,
        content_converter,
        wire_capture=wire_capture,
        context=context,
    )
