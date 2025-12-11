"""
FastAPI response adapters.

This module contains adapters for converting domain response objects
to FastAPI/Starlette response objects.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
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
from src.core.services.steering_leak_protection import get_steering_leak_protector
from src.core.services.streaming.stream_context_registry import (
    get_global_streaming_context_registry,
)

logger = logging.getLogger(__name__)


def _chunk_signals_done(content: Any, metadata: dict[str, Any] | None) -> bool:
    """Detect if a streaming chunk signals end-of-stream."""

    def _has_meaningful_payload(payload: Any) -> bool:
        """Check whether a chunk carries assistant content, tool calls, or usage."""
        if payload is None:
            return False

        if isinstance(payload, dict):
            usage_block = payload.get("usage")
            if isinstance(usage_block, dict):
                return True

            choices = payload.get("choices")
            if isinstance(choices, list) and choices:
                first_choice = choices[0]
                if isinstance(first_choice, dict):
                    delta = first_choice.get("delta") or first_choice.get("message")
                    if isinstance(delta, dict) and any(
                        delta.get(key)
                        for key in (
                            "content",
                            "tool_calls",
                            "reasoning_content",
                            "reasoning",
                        )
                    ):
                        return True

            return bool(payload)

        return bool(payload)

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

    # Honor explicit done markers propagated via metadata
    if metadata and metadata.get("is_done") is True:
        return True

    # Treat explicit terminal events as done only when the chunk is otherwise empty
    if normalized_event in {
        "message_stop",
        "message_done",
    } and not _has_meaningful_payload(content):
        return True

    if metadata:
        finish_reason = metadata.get("finish_reason")
        normalized_reason = (
            finish_reason.strip().lower() if isinstance(finish_reason, str) else None
        )
        if normalized_reason in {
            "error",
            "cancelled",
            "user_cancelled",
            "system_cancelled",
        } and not _has_meaningful_payload(content):
            return True

    # Check if content is a stop chunk with usage (final SSE chunk)
    # This should be treated as is_done=True for proper serialization
    if isinstance(content, dict):
        choices = content.get("choices", [])
        if choices and isinstance(choices, list):
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                fr = first_choice.get("finish_reason")
                if fr in ("stop", "tool_calls", "length"):
                    # Final chunk with finish_reason should signal done
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
        # Use dict(chunk) to safely convert StopChunkWithUsage to plain dict.
        # StopChunkWithUsage is a dict subclass that raises an error on str(),
        # but json.dumps() doesn't call __str__(), so we need to explicitly
        # convert to plain dict to avoid accidental stringification elsewhere.
        # Format as SSE: data: {json}\n\n
        sse_line = f"data: {json.dumps(dict(chunk))}\n\n"
        return sse_line.encode("utf-8")
    elif isinstance(chunk, str):
        return chunk.encode()
    elif isinstance(chunk, bytes):
        return chunk
    else:
        return str(chunk).encode("utf-8")


def _normalize_content(content: Any) -> Any:
    """Normalize content into JSON-serializable structures when possible."""
    # Preserve StopChunkWithUsage - it's a dict subclass that must not be converted
    # to a plain dict, otherwise its stringification protection is lost
    from src.core.ports.streaming_contracts import StopChunkWithUsage

    if isinstance(content, StopChunkWithUsage):
        return content
    if hasattr(content, "model_dump"):
        try:
            return content.model_dump()
        except (TypeError, ValueError, AttributeError):
            if logger.isEnabledFor(logging.DEBUG):
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
    elif isinstance(content, str) and content:
        # Preserve whitespace-only content (spaces, newlines) - don't use .strip()
        if streaming:
            target_payload["content"] = content
        else:
            target_payload.setdefault("content", content)
    elif content not in (None, ""):
        # For non-string content, convert and preserve as-is
        rendered = str(content)
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

    # For non-streaming responses with tool_calls in metadata but simple content,
    # we need to build an OpenAI-style payload to include the tool_calls
    tool_calls = metadata.get("tool_calls")
    if not streaming and isinstance(tool_calls, list) and tool_calls:
        return _build_streaming_payload(
            normalized_content, metadata, None, streaming=False
        )

    return normalized_content


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

    forced_done = False
    if data_lines and data_lines[-1] in ("[DONE]", '["DONE"]'):
        forced_done = True
        data_lines = data_lines[:-1]

    # Nothing but a done marker
    if not data_lines:
        return "", {"finish_reason": "stop"}, True

    data_body = "\n".join(data_lines).strip()
    if data_body in ("[DONE]", '["DONE"]'):
        return "", {"finish_reason": "stop"}, True

    metadata_hint: dict[str, Any] = {}
    try:
        decoded = json.loads(data_body)
    except json.JSONDecodeError:
        if forced_done:
            metadata_hint["finish_reason"] = "stop"
        return data_body, metadata_hint, forced_done

    finish_reason = decoded.get("finish_reason")
    if finish_reason:
        metadata_hint["finish_reason"] = finish_reason
    elif forced_done:
        metadata_hint["finish_reason"] = "stop"

    event_type = decoded.get("type")
    if isinstance(event_type, str):
        metadata_hint["event_type"] = event_type.strip().lower()

    return decoded, metadata_hint, forced_done


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

    prepared_content = _prepare_json_content(content)

    if envelope.metadata and isinstance(prepared_content, dict):
        reasoning_meta = envelope.metadata.get("reasoning") or envelope.metadata.get(
            "reasoning_content"
        )
        if reasoning_meta:
            metadata_section = prepared_content.setdefault("metadata", {})
            if isinstance(metadata_section, dict):
                metadata_section.setdefault("reasoning", reasoning_meta)
                metadata_section.setdefault("reasoning_content", reasoning_meta)

        if envelope.metadata.get("steering_retry_occurred"):
            metadata_section = prepared_content.setdefault("metadata", {})
            if isinstance(metadata_section, dict):
                metadata_section["steering_retry_occurred"] = True

    prepared_content, usage_data = _ensure_usage(envelope, prepared_content, context)
    headers = _apply_usage_headers(headers, usage_data)

    if media_type and media_type.startswith("application/json"):
        # Surface middleware metadata such as reasoning streams when available.
        if envelope.metadata and isinstance(prepared_content, dict):
            metadata_reasoning = envelope.metadata.get(
                "reasoning"
            ) or envelope.metadata.get("reasoning_content")
            if metadata_reasoning:
                metadata_block = prepared_content.setdefault("metadata", {})
                if isinstance(metadata_block, dict):
                    metadata_block.setdefault("reasoning", metadata_reasoning)

        safe_content = _sanitize_json_content(prepared_content)
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
            content=domain_response.model_dump(),
            headers=None,
            status_code=200,
            usage=domain_response.usage,
            metadata=(
                {"model": domain_response.model} if domain_response.model else None
            ),
        )
    elif isinstance(domain_response, ProcessedResponse):
        return ResponseEnvelope(
            content=domain_response.content,
            headers=None,
            status_code=200,
            usage=domain_response.usage,
            metadata=domain_response.metadata,
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


def _normalize_usage_dict(usage: Any) -> dict[str, Any] | None:
    """Normalize a usage dictionary to OpenRouter-compatible format.

    Preserves extended fields (reasoning_tokens, cached_tokens, cost) when present.
    """
    if not isinstance(usage, dict):
        return None

    try:
        from src.core.domain.openrouter_usage import OpenRouterUsage

        parsed = OpenRouterUsage.from_dict(usage)
        if parsed is not None:
            return parsed.to_openrouter_dict()

        # Fallback to basic normalization
        return {
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        }
    except Exception:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Failed to normalize usage payload: %s", usage, exc_info=True)
        return None


def _resolve_model_name(envelope: ResponseEnvelope, payload: Any) -> str | None:
    """Extract model name from envelope metadata or payload."""
    if isinstance(payload, dict):
        model_name = payload.get("model") or payload.get("id")
        if isinstance(model_name, str) and model_name:
            return model_name

    metadata = getattr(envelope, "metadata", None)
    if isinstance(metadata, dict):
        model_name = metadata.get("model")
        if isinstance(model_name, str) and model_name:
            return model_name
    return None


def _resolve_prompt_tokens(
    usage: dict[str, int] | None, envelope: ResponseEnvelope
) -> int | None:
    """Get prompt tokens from usage or outbound token metadata."""
    if usage and isinstance(usage.get("prompt_tokens"), int):
        prompt_tokens = usage["prompt_tokens"]
        if prompt_tokens > 0:
            return prompt_tokens

    metadata = getattr(envelope, "metadata", None)
    if isinstance(metadata, dict):
        outbound_tokens = metadata.get("outbound_tokens")
        if isinstance(outbound_tokens, int | float):
            try:
                return int(outbound_tokens)
            except (TypeError, ValueError):
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to coerce outbound_tokens: %s", outbound_tokens
                    )
    return None


def _calculate_completion_tokens(payload: Any, model_name: str | None) -> int | None:
    """Calculate completion tokens from the response payload."""
    text_value: str | None = None
    if isinstance(payload, dict):
        from src.core.utils.usage_recalculation import (
            extract_content_text,
            should_recalculate_usage,
        )

        if should_recalculate_usage(payload):
            text_value = extract_content_text(payload)
    elif isinstance(payload, str):
        text_value = payload

    if text_value:
        from src.core.utils.token_count import count_tokens

        try:
            return count_tokens(text_value, model=model_name)
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Failed to calculate completion tokens", exc_info=True)
    return None


def _should_replace_completion(existing_tokens: int, recalculated_tokens: int) -> bool:
    """Decide if recalculated completion tokens should replace existing values."""
    if existing_tokens == 0:
        return True

    token_diff = abs(existing_tokens - recalculated_tokens)
    if token_diff > 10:
        return True

    try:
        return token_diff / existing_tokens > 0.05
    except Exception:
        return False


def _ensure_usage(
    envelope: ResponseEnvelope,
    payload: Any,
    context: RequestContext | None = None,
) -> tuple[Any, dict[str, Any] | None]:
    """Ensure usage information is present and aligned with transformed content.

    This function now integrates with the UsageCalculationService to:
    1. Use backend-provided usage when available
    2. Recalculate when proxy modifications occurred
    3. Preserve extended usage fields (reasoning_tokens, cached_tokens, cost)

    Args:
        envelope: The response envelope
        payload: The response payload
        context: Request context with modification tracking

    Returns:
        Tuple of (updated payload, usage dict in OpenRouter format)
    """
    from src.core.services.usage_calculation_service import (
        get_usage_calculation_service,
    )

    # Get existing usage from envelope or payload
    existing_usage = _normalize_usage_dict(envelope.usage)
    if existing_usage is None and isinstance(payload, dict):
        existing_usage = _normalize_usage_dict(payload.get("usage"))

    model_name = _resolve_model_name(envelope, payload)

    # Check if modifications require recalculation
    requires_recalc = False
    if context is not None:
        requires_recalc = context.requires_usage_recalculation()

    # Check metadata for recalculation flag
    metadata = getattr(envelope, "metadata", None)
    if isinstance(metadata, dict) and metadata.get("allow_usage_recalculation"):
        requires_recalc = True

    # Use the service for proper usage calculation
    service = get_usage_calculation_service()

    if requires_recalc or existing_usage is None:
        # Get prompt tokens hint from metadata
        prompt_tokens_hint = _resolve_prompt_tokens(existing_usage, envelope)

        # Recalculate usage accounting for modifications
        usage = service.ensure_usage(
            backend_usage=existing_usage,
            context=context,
            response_content=payload,
            model=model_name,
            force_recalculation=requires_recalc,
        )

        # Apply prompt tokens hint if we got one from metadata.
        # The hint (outbound_tokens) is calculated by the proxy from the actual request
        # being sent, so it's the most accurate measure. Use it when larger than reported.
        if prompt_tokens_hint is not None and prompt_tokens_hint > 0:
            current_prompt = usage.get("prompt_tokens", 0) or 0
            if prompt_tokens_hint > current_prompt:
                usage["prompt_tokens"] = prompt_tokens_hint
                usage["total_tokens"] = usage.get("prompt_tokens", 0) + usage.get(
                    "completion_tokens", 0
                )
    else:
        # Use existing usage, ensuring it's normalized
        usage = existing_usage

        # Still check if completion tokens need recalculation based on content
        completion_tokens = _calculate_completion_tokens(payload, model_name)
        if completion_tokens is not None:
            existing_completion = int(usage.get("completion_tokens", 0) or 0)
            if _should_replace_completion(existing_completion, completion_tokens):
                if existing_completion != completion_tokens and logger.isEnabledFor(
                    logging.INFO
                ):
                    logger.info(
                        "Usage completion tokens recalculated: %s -> %s",
                        existing_completion,
                        completion_tokens,
                    )
                usage["completion_tokens"] = completion_tokens
                usage["total_tokens"] = (
                    usage.get("prompt_tokens", 0) + completion_tokens
                )

    # Apply usage to envelope and payload
    usage_to_apply: dict[str, Any] | None = usage if usage else None

    if usage_to_apply:
        envelope.usage = usage_to_apply
        if isinstance(payload, dict):
            payload["usage"] = usage_to_apply

    return payload, usage_to_apply


def _apply_usage_headers(
    headers: dict[str, Any] | None, usage: dict[str, Any] | None
) -> dict[str, Any]:
    """Attach usage details as response headers for clients.

    Includes both basic token counts and extended fields when available:
    - x-usage-prompt-tokens
    - x-usage-completion-tokens
    - x-usage-total-tokens
    - x-usage-reasoning-tokens (if available)
    - x-usage-cached-tokens (if available)
    - x-usage-cost (if available)
    """
    merged_headers: dict[str, Any] = dict(headers or {})
    if not usage:
        return merged_headers

    def _coerce_int(value: int | float | None) -> str:
        try:
            return str(int(value or 0))
        except Exception:
            return "0"

    def _coerce_float(value: float | None) -> str | None:
        if value is None:
            return None
        try:
            return str(float(value))
        except Exception:
            return None

    # Basic token counts (always included)
    merged_headers["x-usage-prompt-tokens"] = _coerce_int(usage.get("prompt_tokens"))
    merged_headers["x-usage-completion-tokens"] = _coerce_int(
        usage.get("completion_tokens")
    )
    merged_headers["x-usage-total-tokens"] = _coerce_int(usage.get("total_tokens"))

    # Extended: completion tokens details
    completion_details = usage.get("completion_tokens_details")
    if isinstance(completion_details, dict):
        reasoning_tokens = completion_details.get("reasoning_tokens")
        if reasoning_tokens is not None:
            merged_headers["x-usage-reasoning-tokens"] = _coerce_int(reasoning_tokens)

    # Extended: prompt tokens details
    prompt_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        cached_tokens = prompt_details.get("cached_tokens")
        if cached_tokens is not None:
            merged_headers["x-usage-cached-tokens"] = _coerce_int(cached_tokens)
        audio_tokens = prompt_details.get("audio_tokens")
        if audio_tokens is not None:
            merged_headers["x-usage-audio-tokens"] = _coerce_int(audio_tokens)

    # Extended: cost
    cost = usage.get("cost")
    cost_str = _coerce_float(cost)
    if cost_str is not None:
        merged_headers["x-usage-cost"] = cost_str

    return merged_headers


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
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Sanitize: Could not check for coroutine: %s", o)
        if async_mock is not None:
            try:
                if isinstance(o, async_mock):
                    return str(o)
            except TypeError:
                if logger.isEnabledFor(logging.DEBUG):
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
    # CRITICAL: Apply steering leak protection as final safety net for non-streaming responses
    # This ensures internal steering data NEVER reaches clients, even if upstream code
    # fails to properly sanitize responses
    protector = get_steering_leak_protector()
    safe_content = content
    if protector.enabled and isinstance(content, dict):
        safe_content, had_leak = protector.sanitize_dict(content)
        if had_leak:
            logger.warning(
                "SECURITY: Sanitized leaked steering data from non-streaming JSON response"
            )

    # Allow provider-specific headers for usage tracking and rate limiting
    allowed_prefixes = ("x-", "access-control-", "anthropic-", "openai-", "zenmux-")
    filtered_headers = {
        k: v
        for k, v in (headers or {}).items()
        if k.lower().startswith(allowed_prefixes)
    }

    response = JSONResponse(
        content=safe_content,
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

    # CRITICAL: Apply steering leak protection as final safety net
    protector = get_steering_leak_protector()

    if isinstance(content, dict | list | tuple):
        try:
            # Use dict(content) if it's a dict to safely handle StopChunkWithUsage
            # which is a dict subclass that raises an error on str()
            safe_content = dict(content) if isinstance(content, dict) else content

            # Sanitize dict content for steering leaks
            if protector.enabled and isinstance(safe_content, dict):
                safe_content, had_leak = protector.sanitize_dict(safe_content)
                if had_leak:
                    logger.warning(
                        "SECURITY: Sanitized leaked steering data from non-JSON response"
                    )

            content_str = json.dumps(safe_content)
        except (TypeError, ValueError):
            content_str = str(content)

    # Also sanitize string content for steering leaks
    if protector.enabled and isinstance(content_str, str):
        content_str, had_leak = protector.sanitize_content(content_str)
        if had_leak:
            logger.warning(
                "SECURITY: Sanitized leaked steering data from string response"
            )

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
    envelope_metadata = (
        domain_response.metadata if isinstance(domain_response.metadata, dict) else {}
    )

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
            try:
                if hasattr(source, "__aiter__"):
                    async for item in source:  # type: ignore[async-for]
                        yield item
                else:
                    for item in source:  # type: ignore[union-attr]
                        yield item
            except GeneratorExit:
                # Close the source iterator if it supports aclose
                if hasattr(source, "aclose"):
                    with contextlib.suppress(Exception):
                        await source.aclose()  # type: ignore[union-attr]
                raise

        def _extract_payload_and_metadata(
            chunk: Any,
        ) -> tuple[Any, dict[str, Any]]:
            if isinstance(chunk, ProcessedResponse):
                return chunk.content, chunk.metadata or {}
            return chunk, {}

        def _extract_usage_from_metadata(
            metadata: dict[str, Any] | None
        ) -> dict[str, Any] | None:
            if not metadata:
                return None
            usage_block = metadata.get("usage")
            return usage_block if isinstance(usage_block, dict) else None

        def _normalize_usage(usage: dict[str, Any] | None) -> dict[str, Any] | None:
            """Coerce usage fields to integers and recompute totals."""
            if not isinstance(usage, dict):
                return None
            normalized = dict(usage)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                try:
                    value = int(normalized.get(key, 0) or 0)
                except Exception:
                    value = 0
                normalized[key] = max(value, 0)
            prompt = normalized.get("prompt_tokens", 0) or 0
            completion = normalized.get("completion_tokens", 0) or 0
            total = normalized.get("total_tokens", 0) or 0
            summed = prompt + completion
            if total < summed:
                normalized["total_tokens"] = summed
            return normalized

        def _merge_usage_max(
            current: dict[str, Any] | None, previous: dict[str, Any] | None
        ) -> dict[str, Any] | None:
            """Combine usage dicts, keeping the highest observed values."""
            normalized_current = _normalize_usage(current)
            normalized_previous = _normalize_usage(previous)
            if normalized_current is None and normalized_previous is None:
                return None
            if normalized_previous is None:
                return normalized_current
            if normalized_current is None:
                return normalized_previous

            merged = dict(normalized_previous)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                merged[key] = max(
                    normalized_previous.get(key, 0) or 0,
                    normalized_current.get(key, 0) or 0,
                )

            # Preserve higher cost when available
            for cost_key in ("cost", "total_cost"):
                prev_cost = normalized_previous.get(cost_key)
                curr_cost = normalized_current.get(cost_key)
                if isinstance(curr_cost, int | float):
                    if not isinstance(prev_cost, int | float) or curr_cost > prev_cost:
                        merged[cost_key] = curr_cost
                elif isinstance(prev_cost, int | float):
                    merged[cost_key] = prev_cost

            for detail_key in (
                "prompt_tokens_details",
                "completion_tokens_details",
                "cost_details",
            ):
                if detail_key not in merged and detail_key in normalized_current:
                    merged[detail_key] = normalized_current[detail_key]
            return merged

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

            forced_done = False
            if data_lines and data_lines[-1] in ("[DONE]", '["DONE"]'):
                forced_done = True
                data_lines = data_lines[:-1]

            # Nothing but a done marker
            if not data_lines:
                return "", {"finish_reason": "stop"}, True

            data_body = "\n".join(data_lines).strip()
            if data_body in ("[DONE]", '["DONE"]'):
                return "", {"finish_reason": "stop"}, True

            metadata_hint: dict[str, Any] = {}
            try:
                decoded = json.loads(data_body)
            except json.JSONDecodeError:
                if forced_done:
                    metadata_hint["finish_reason"] = "stop"
                return data_body, metadata_hint, forced_done

            finish_reason = decoded.get("finish_reason")
            if finish_reason:
                metadata_hint["finish_reason"] = finish_reason
            elif forced_done:
                metadata_hint["finish_reason"] = "stop"

            event_type = decoded.get("type")
            if isinstance(event_type, str):
                metadata_hint["event_type"] = event_type.strip().lower()

            return decoded, metadata_hint, forced_done

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

        def _extract_text_for_usage(payload: Any) -> str:
            """Extract textual content for usage calculation without mutating the payload."""
            if isinstance(payload, dict):
                text_parts: list[str] = []
                choices = payload.get("choices")
                if isinstance(choices, list):
                    for choice in choices:
                        if not isinstance(choice, dict):
                            continue
                        block = choice.get("delta") or choice.get("message") or {}
                        if not isinstance(block, dict):
                            continue
                        content_val = block.get("content")
                        if isinstance(content_val, str) and content_val:
                            text_parts.append(content_val)
                    if text_parts:
                        return "".join(text_parts)

                for key in ("content", "text"):
                    candidate = payload.get(key)
                    if isinstance(candidate, str) and candidate:
                        return candidate
                return ""

            if isinstance(payload, bytes | bytearray):
                try:
                    return payload.decode("utf-8")
                except Exception:
                    return payload.decode("utf-8", errors="ignore")
            if isinstance(payload, str):
                return payload
            return ""

        def _resolve_prompt_hint(
            metadata: dict[str, Any] | None, envelope_meta: dict[str, Any]
        ) -> int:
            """Find outbound/prompt token hint from chunk metadata or envelope metadata."""
            for source in (metadata, envelope_meta):
                if not isinstance(source, dict):
                    continue
                outbound_tokens = source.get("outbound_tokens")
                if isinstance(outbound_tokens, int | float):
                    try:
                        return int(outbound_tokens)
                    except Exception:
                        continue
            return 0

        def _resolve_stream_key(metadata: dict[str, Any]) -> str:
            # Priority: stream_id (from StreamNormalizer) > session_id (consistent per request) > id (per-chunk, NOT suitable for buffering)
            # IMPORTANT: Do NOT use "id" as it's different for each chunk (e.g., chatcmpl-xxx)
            # and will break tool call buffering across chunks
            for candidate_key in ("stream_id", "session_id"):
                value = metadata.get(candidate_key)
                if isinstance(value, str) and value:
                    return value
            return "anonymous-stream"

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

        def _update_tracked_tags(stream_key: str, text_value: str) -> list[str]:
            tags: list[str] = []
            try:
                buffer_state = context_registry.get_tool_call_buffer(stream_key)
                disallowed_tags = (
                    {"think", "thought"} if not buffer_state.allowed_tools else set()
                )
            except Exception:
                buffer_state = None
                disallowed_tags = {"think", "thought"}
            if not text_value:
                return tags
            for match in re.finditer(r"<([A-Za-z0-9_\\-]+)(?=[\\s>/])", text_value):
                tag = match.group(1)
                if text_value[match.start() + 1] == "/":
                    continue
                tail = text_value[match.end() : match.end() + 2]
                if tail.startswith("/"):
                    continue  # self-closing tag
                if tag.lower() in disallowed_tags:
                    continue
                tags.append(tag)
            if buffer_state is not None and tags:
                buffer_state.tracked_tags.update(tags)
            return tags

        def _get_target_tags(
            stream_key: str, text_value: str | None
        ) -> tuple[str, ...]:
            """Get target tool tags using allowed tools and observed tags."""
            try:
                buffer_state = context_registry.get_tool_call_buffer(stream_key)
                allowed = list(buffer_state.allowed_tools or [])
                tracked = list(buffer_state.tracked_tags)
            except Exception:
                allowed = []
                tracked = []

            ordered_tags: list[str] = []
            observed_in_text = (
                _update_tracked_tags(stream_key, text_value) if text_value else []
            )
            for tag in observed_in_text:
                if tag not in ordered_tags:
                    ordered_tags.append(tag)

            for tag in tracked:
                if tag not in ordered_tags:
                    ordered_tags.append(tag)

            for tag in allowed:
                if tag not in ordered_tags:
                    ordered_tags.append(tag)

            return tuple(ordered_tags)

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
            target_tags = _get_target_tags(stream_key, text_value)
            for tag in target_tags:
                updated_text = _apply_tag_buffer(stream_key, tag, updated_text)

            if updated_text != text_value:
                delta["content"] = updated_text

        def _flush_pending_tool_blocks(stream_key: str, payload: Any) -> None:
            pending_fragments: list[str] = []
            target_tags = _get_target_tags(stream_key, None)
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
                accumulated_text_parts: list[str] = []
                best_usage: dict[str, Any] | None = None
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
                    if (
                        isinstance(envelope_metadata, dict)
                        and "outbound_tokens" in envelope_metadata
                        and "outbound_tokens" not in metadata
                    ):
                        # Defensive: keep streaming even if assignment fails
                        with contextlib.suppress(Exception):
                            metadata["outbound_tokens"] = envelope_metadata[
                                "outbound_tokens"
                            ]

                    stream_key = _resolve_stream_key(metadata)
                    _sanitize_multiline_tool_blocks(stream_key, decoded_payload)

                    # Inject reasoning metadata for OpenAI-style payloads
                    enriched = _inject_reasoning_metadata(
                        decoded_payload, metadata, streaming=True
                    )

                    usage_payload = (
                        enriched.get("usage") if isinstance(enriched, dict) else None
                    )
                    computed_usage = (
                        usage_payload if isinstance(usage_payload, dict) else None
                    )
                    if computed_usage is None:
                        computed_usage = _extract_usage_from_metadata(metadata)
                    best_usage = _merge_usage_max(computed_usage, best_usage)

                    text_for_usage = _extract_text_for_usage(enriched)
                    if text_for_usage:
                        accumulated_text_parts.append(text_for_usage)

                    # Check if this chunk signals completion
                    is_done = forced_done or _chunk_signals_done(enriched, metadata)

                    if is_done:
                        _flush_pending_tool_blocks(stream_key, decoded_payload)

                        accumulated_content = None
                        if isinstance(metadata, dict):
                            accumulated_value = metadata.get("accumulated_content")
                            if isinstance(accumulated_value, str):
                                accumulated_content = accumulated_value

                        model_name = None
                        if isinstance(metadata, dict):
                            model_candidate = metadata.get("model")
                            if isinstance(model_candidate, str):
                                model_name = model_candidate
                        if model_name is None:
                            envelope_model = envelope_metadata.get("model")
                            if isinstance(envelope_model, str):
                                model_name = envelope_model

                        force_usage_recalc = False
                        if (
                            isinstance(metadata, dict)
                            and metadata.get("allow_usage_recalculation")
                            or envelope_metadata.get("allow_usage_recalculation")
                        ):
                            force_usage_recalc = True
                        elif context is not None:
                            try:
                                force_usage_recalc = (
                                    context.requires_usage_recalculation()
                                )
                            except Exception:
                                force_usage_recalc = False

                        if accumulated_content is None:
                            accumulated_content = "".join(accumulated_text_parts)

                        prompt_hint = _resolve_prompt_hint(metadata, envelope_metadata)

                        try:
                            from src.core.services.usage_calculation_service import (
                                get_usage_calculation_service,
                            )

                            service = get_usage_calculation_service()
                            computed_usage = service.merge_streaming_usage(
                                accumulated_content=accumulated_content or "",
                                final_chunk_usage=computed_usage,
                                context=context,
                                model=model_name,
                                force_recalculation=force_usage_recalc,
                            )

                            normalized_usage = _normalize_usage(computed_usage) or {}
                            # Preserve prompt tokens from earlier hints/usages
                            if isinstance(best_usage, dict):
                                prompt_from_best = (
                                    best_usage.get("prompt_tokens", 0) or 0
                                )
                                if prompt_from_best > normalized_usage.get(
                                    "prompt_tokens", 0
                                ):
                                    normalized_usage["prompt_tokens"] = prompt_from_best

                            # The prompt_hint (outbound_tokens) is calculated by the proxy
                            # from the actual request being sent to the backend. This is the
                            # most accurate measure of input tokens. Use it when it's larger
                            # than what was reported by the backend or accumulated so far.
                            if prompt_hint > 0:
                                current_prompt = (
                                    normalized_usage.get("prompt_tokens", 0) or 0
                                )
                                if prompt_hint > current_prompt:
                                    normalized_usage["prompt_tokens"] = prompt_hint

                            # For completion tokens, honor recalculation when requested,
                            # otherwise keep the higher value to avoid regressions.
                            if isinstance(best_usage, dict):
                                best_completion = (
                                    best_usage.get("completion_tokens", 0) or 0
                                )
                                if not force_usage_recalc and (
                                    best_completion
                                    > normalized_usage.get("completion_tokens", 0)
                                ):
                                    normalized_usage["completion_tokens"] = (
                                        best_completion
                                    )

                            # Recompute totals after adjustments
                            prompt_val = normalized_usage.get("prompt_tokens", 0) or 0
                            completion_val = (
                                normalized_usage.get("completion_tokens", 0) or 0
                            )
                            normalized_usage["total_tokens"] = (
                                prompt_val + completion_val
                            )

                            # Preserve higher cost if we had one before
                            if isinstance(best_usage, dict):
                                for cost_key in ("cost", "total_cost"):
                                    prev_cost = best_usage.get(cost_key)
                                    curr_cost = normalized_usage.get(cost_key)
                                    if isinstance(prev_cost, int | float) and (
                                        not isinstance(curr_cost, int | float)
                                        or prev_cost > curr_cost
                                    ):
                                        normalized_usage[cost_key] = prev_cost

                            best_usage = (
                                normalized_usage if normalized_usage else best_usage
                            )

                            if isinstance(best_usage, dict) and isinstance(
                                enriched, dict
                            ):
                                try:
                                    enriched["usage"] = best_usage
                                except Exception:
                                    enriched = dict(enriched)
                                    enriched["usage"] = best_usage
                        except Exception:
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "Failed to merge streaming usage", exc_info=True
                                )

                    streaming_content = StreamingContent(
                        content=enriched,
                        metadata=metadata,
                        is_done=is_done,
                        stream_id=metadata.get("stream_id") if metadata else None,
                        usage=best_usage if isinstance(best_usage, dict) else None,
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

            except GeneratorExit:
                # Client disconnected - this is expected, don't log as error
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("[STREAMING] Client disconnected during stream")
                raise
            except Exception as e:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Error during streaming content conversion: %s",
                        e,
                        exc_info=True,
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

        try:
            async for sse_chunk in sse_bytes_iter:
                yield sse_chunk
                await asyncio.sleep(0)
        except GeneratorExit:
            # Client disconnected - clean up the SSE iterator
            if hasattr(sse_bytes_iter, "aclose"):
                with contextlib.suppress(Exception):
                    await sse_bytes_iter.aclose()
            raise

    content_iter = domain_response.content
    if content_iter is None:
        # Create empty iterator if content is None
        async def _empty_streamer() -> AsyncIterator[bytes]:
            for _ in ():
                yield b""

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
