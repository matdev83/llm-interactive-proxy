"""
FastAPI response adapters.

This module provides backward-compatible public API for response adaptation.
All logic is delegated to focused layer modules under adapters/.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from datetime import datetime, timezone
from typing import Any, TypeVar, cast

from fastapi.responses import Response
from pydantic.types import JsonValue
from starlette.responses import StreamingResponse

from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.chat import ChatResponse, StreamingChatResponse
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.translation_utils.json_utils import sanitize_dict_for_json
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.wire_capture_interface import IWireCapture

# Import SSEAssembler for streaming conversion
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_orchestrator import safe_aclose

# Import layer implementations
from src.core.transport.fastapi.adapters.capture.wire_capture_coordinator import (
    WireCaptureCoordinator,
)
from src.core.transport.fastapi.adapters.response.json_response_builder import (
    JSONResponseBuilder,
)
from src.core.transport.fastapi.adapters.response.other_response_builder import (
    OtherResponseBuilder,
)
from src.core.transport.fastapi.adapters.response.streaming_response_builder import (
    StreamingResponseBuilder,
    _never_emit_stream_bytes,
)
from src.core.transport.fastapi.adapters.streaming.content_converter import (
    StreamingContentConverter,
)
from src.core.transport.fastapi.adapters.usage.header_injector import (
    UsageHeaderInjector,
)

T = TypeVar("T")

logger = logging.getLogger(__name__)

_STREAM_DISCONNECT_CLOSE_TIMEOUT_S = 1.0
_STREAM_DISCONNECT_SLOW_CLOSE_THRESHOLD_S = 0.5


def _schedule_stream_close(
    stream: Any,
    *,
    name: str,
    request_id: str | None,
) -> None:
    if stream is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Skipping stream cleanup scheduling; no running event loop",
                exc_info=True,
            )
        return

    async def _close() -> None:
        start = time.perf_counter()
        try:
            await safe_aclose(stream, timeout_s=_STREAM_DISCONNECT_CLOSE_TIMEOUT_S)
        except Exception as exc:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Stream cleanup failed for %s: %s",
                    name,
                    exc,
                    exc_info=True,
                )
        finally:
            duration_s = time.perf_counter() - start
            if duration_s >= _STREAM_DISCONNECT_SLOW_CLOSE_THRESHOLD_S:
                extra = {"request_id": request_id} if request_id else None
                logger.warning(
                    "Slow stream cleanup after client disconnect: stream=%s duration_ms=%.2f",
                    name,
                    duration_s * 1000.0,
                    extra=extra,
                )

    try:
        task = loop.create_task(_close())
        task.add_done_callback(lambda t: t.exception())
    except RuntimeError:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to schedule stream cleanup task",
                exc_info=True,
            )


def _schedule_disconnect_cleanup(
    cleanup: Callable[[], Coroutine[Any, Any, None]],
    *,
    request_id: str | None,
) -> None:
    """Schedule disconnect cleanup without blocking stream shutdown."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Skipping disconnect cleanup scheduling; no running event loop",
                exc_info=True,
            )
        return

    def _consume_task_exception(task: asyncio.Task[None]) -> None:
        try:
            task.exception()
        except asyncio.CancelledError:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Disconnect cleanup task cancelled",
                    extra={"request_id": request_id},
                )
        except Exception:
            # Exception is already consumed from task.exception();
            # this guard prevents callback-level crashes.
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Failed to consume disconnect cleanup task exception",
                    extra={"request_id": request_id},
                    exc_info=True,
                )

    try:
        task: asyncio.Task[None] = loop.create_task(cleanup())
        task.add_done_callback(_consume_task_exception)
    except RuntimeError:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to schedule disconnect cleanup task",
                exc_info=True,
            )


async def _handle_client_stream_disconnect(
    *,
    domain_response: StreamingResponseEnvelope,
    context: RequestContext | None,
    request_id: str | None,
    cancel_reason: str,
    details: str,
    termination_reason: Any,
) -> None:
    """Run explicit stream cancel + session-scoped cancellation report."""
    if context is not None:
        context.ensure_processing_context().update({"cancel_reason": cancel_reason})

    cancel_callback = getattr(domain_response, "cancel_callback", None)
    if callable(cancel_callback):
        try:
            cancellation_result = cancel_callback()
            if isinstance(cancellation_result, Awaitable):
                await cancellation_result
            elif cancellation_result is not None:
                logger.warning(
                    "Streaming cancel callback returned non-awaitable result",
                    extra={"request_id": request_id},
                )
        except Exception as exc:
            logger.warning(
                "Failed to run streaming cancel callback on disconnect: %s",
                exc,
                exc_info=True,
                extra={"request_id": request_id},
            )

    if context is None:
        return

    from src.core.domain.client_termination import ClientEndOfSessionSignal
    from src.core.interfaces.client_end_of_session_service_interface import (
        IClientEndOfSessionService,
    )
    from src.core.transport.session_key_resolver import (
        resolve_session_key_from_request_context,
    )

    session_key = resolve_session_key_from_request_context(context)
    if session_key is None:
        return

    client_eos_service = _resolve_service(
        cast(type[IClientEndOfSessionService], IClientEndOfSessionService)
    )
    if client_eos_service is None:
        return

    signal = ClientEndOfSessionSignal(
        session_key=session_key,
        observed_at=datetime.now(timezone.utc),
        reason=termination_reason,
        details=details,
    )

    try:
        # Avoid asyncio.shield here: on server shutdown the loop may be closing and
        # shield schedules work that outlives the disconnect cleanup task, causing
        # "Task was destroyed but it is pending" noise. Fire-and-forget scheduling
        # already isolates this path from the streaming generator.
        await client_eos_service.report_client_termination(signal)
    except Exception as exc:
        logger.warning(
            "Failed to report client stream termination: %s",
            exc,
            exc_info=True,
            extra={"request_id": request_id},
        )


def _is_mock_object(value: Any) -> bool:
    module_name = getattr(type(value), "__module__", "")
    return isinstance(module_name, str) and module_name.startswith("unittest.mock")


# Lazy singleton instances
_json_builder: JSONResponseBuilder | None = None
_streaming_builder: StreamingResponseBuilder | None = None
_other_builder: OtherResponseBuilder | None = None
_content_converter: StreamingContentConverter | None = None
_sse_assembler: SSEAssembler | None = None
_wire_capture_coordinator: WireCaptureCoordinator | None = None
_usage_header_injector: UsageHeaderInjector | None = None

# Locks for thread-safe singleton initialization (synchronized double-checked locking)
_json_builder_lock = threading.Lock()
_streaming_builder_lock = threading.Lock()
_other_builder_lock = threading.Lock()
_content_converter_lock = threading.Lock()
_sse_assembler_lock = threading.Lock()
_wire_capture_coordinator_lock = threading.Lock()
_usage_header_injector_lock = threading.Lock()


def _resolve_service(service_type: type[T]) -> T | None:
    """Resolve a service from DI if available.

    Returns None when DI is unavailable or service is not registered.
    """
    try:
        from src.core.di.services import get_service_provider

        provider = get_service_provider()
        return provider.get_service(service_type)
    except ImportError as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Failed to import DI services module: %s, returning None for service %s",
                e,
                service_type.__name__,
                exc_info=True,
            )
        return None
    except (AttributeError, KeyError) as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Service %s not registered in DI provider: %s, returning None",
                service_type.__name__,
                e,
                exc_info=True,
            )
        return None
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Unexpected error resolving service %s: %s, returning None",
                service_type.__name__,
                e,
                exc_info=True,
            )
        return None


def _get_usage_header_injector() -> UsageHeaderInjector:
    """Get or create usage header injector singleton."""
    global _usage_header_injector
    if _usage_header_injector is None or _is_mock_object(_usage_header_injector):
        with _usage_header_injector_lock:
            if _usage_header_injector is None or _is_mock_object(
                _usage_header_injector
            ):
                _usage_header_injector = (
                    _resolve_service(UsageHeaderInjector) or UsageHeaderInjector()
                )
    return _usage_header_injector


def _apply_usage_headers(
    headers: dict[str, str] | None,
    usage: dict[str, object] | None,
) -> dict[str, str]:
    """Backward-compatible helper to inject usage headers.

    Some tests (and legacy code) import this helper directly. The implementation
    lives in the adapter layer (UsageHeaderInjector), so we keep a thin wrapper
    here to preserve the old public surface.
    """
    if headers is None:
        headers = {}
    if usage is None:
        return dict(headers)
    return _get_usage_header_injector().inject_headers(dict(headers), usage)


def _resolve_b2bua_echo_header(
    context: RequestContext | None,
) -> tuple[str, str] | None:
    if context is None:
        return None
    identity = getattr(context, "b2bua_identity", None)
    if not isinstance(identity, B2buaIdentity):
        return None
    a_session_id = identity.a_session_id.strip()
    if not a_session_id:
        return None

    header_name = "x-b2bua-session-id"
    echo_enabled = False

    config_candidates: list[Any] = []
    app_state = getattr(context, "app_state", None)
    if app_state is not None:
        for attribute_name in ("app_config", "config"):
            try:
                config_candidate = getattr(app_state, attribute_name, None)
            except Exception:
                # Some secure state proxies intentionally block direct config access.
                continue
            if config_candidate is not None and not _is_mock_object(config_candidate):
                config_candidates.append(config_candidate)

    from src.core.interfaces.configuration_interface import IConfig

    config_candidates.append(_resolve_service(IConfig))

    for config in config_candidates:
        if config is None or _is_mock_object(config):
            continue
        b2bua_cfg = getattr(getattr(config, "session", None), "b2bua", None)
        if b2bua_cfg is None:
            continue
        echo_enabled = bool(getattr(b2bua_cfg, "echo_enabled", False))
        configured_name = getattr(b2bua_cfg, "echo_header_name", None)
        if isinstance(configured_name, str) and configured_name.strip():
            header_name = configured_name.strip().lower()
        break

    if not echo_enabled:
        return None
    return header_name, a_session_id


def _apply_b2bua_echo_header(
    headers: dict[str, str] | None,
    context: RequestContext | None,
) -> dict[str, str]:
    result_headers = dict(headers or {})
    resolved = _resolve_b2bua_echo_header(context)
    if resolved is None:
        return result_headers
    header_name, a_session_id = resolved
    result_headers[header_name] = a_session_id
    return result_headers


def _get_json_builder() -> JSONResponseBuilder:
    """Get or create JSON response builder singleton."""
    global _json_builder
    if _json_builder is None or _is_mock_object(_json_builder):
        with _json_builder_lock:
            if _json_builder is None or _is_mock_object(_json_builder):
                resolved = _resolve_service(JSONResponseBuilder)
                _json_builder = (
                    resolved
                    if resolved is not None and not _is_mock_object(resolved)
                    else JSONResponseBuilder()
                )
    return _json_builder


def _get_other_builder() -> OtherResponseBuilder:
    """Get or create other response builder singleton."""
    global _other_builder
    if _other_builder is None or _is_mock_object(_other_builder):
        with _other_builder_lock:
            if _other_builder is None or _is_mock_object(_other_builder):
                resolved = _resolve_service(OtherResponseBuilder)
                _other_builder = (
                    resolved
                    if resolved is not None and not _is_mock_object(resolved)
                    else OtherResponseBuilder()
                )
    return _other_builder


def _get_content_converter(yield_interval: int = 100) -> StreamingContentConverter:
    """Get or create streaming content converter singleton."""
    global _content_converter
    if _content_converter is None or _is_mock_object(_content_converter):
        with _content_converter_lock:
            if _content_converter is None or _is_mock_object(_content_converter):
                # Try to resolve from DI first
                converter = _resolve_service(StreamingContentConverter)

                if converter is None:
                    # Manually create with dependencies from DI if available
                    # This ensures we share the StreamingContextRegistry singleton
                    # to prevent memory leaks from split registry instances
                    from src.core.services.streaming.stream_context_registry import (
                        StreamingContextRegistry,
                    )
                    from src.core.transport.fastapi.adapters.streaming.tool_block_buffer import (
                        ToolBlockBuffer,
                    )

                    registry = _resolve_service(StreamingContextRegistry)
                    tool_block_buffer = None
                    if registry:
                        tool_block_buffer = ToolBlockBuffer(registry=registry)

                    converter = StreamingContentConverter(
                        tool_block_buffer=tool_block_buffer,
                        yield_interval=yield_interval,
                    )

                _content_converter = converter

    # If a caller asks for a different yield_interval than the cached instance was
    # constructed with, rebuild to keep test isolation and avoid surprising behavior.
    try:
        current_interval = getattr(_content_converter, "yield_interval", None)
        if isinstance(current_interval, int) and current_interval != yield_interval:
            with _content_converter_lock:
                converter = StreamingContentConverter(
                    tool_block_buffer=getattr(
                        _content_converter, "tool_block_buffer", None
                    ),
                    yield_interval=yield_interval,
                )
                _content_converter = converter
    except Exception:
        # Best-effort; if rebuilding fails, keep the existing instance.
        pass
    return _content_converter


def _get_sse_assembler(yield_interval: int = 100) -> SSEAssembler:
    """Get or create SSE assembler singleton."""
    global _sse_assembler
    if _sse_assembler is None or _is_mock_object(_sse_assembler):
        with _sse_assembler_lock:
            if _sse_assembler is None or _is_mock_object(_sse_assembler):
                _sse_assembler = _resolve_service(SSEAssembler) or SSEAssembler(
                    yield_interval=yield_interval
                )
    return _sse_assembler


def _get_wire_capture_coordinator(
    wire_capture: IWireCapture | None,
) -> WireCaptureCoordinator:
    """Get or create wire capture coordinator singleton."""
    global _wire_capture_coordinator
    if _wire_capture_coordinator is None:
        with _wire_capture_coordinator_lock:
            if _wire_capture_coordinator is None:
                _wire_capture_coordinator = WireCaptureCoordinator(
                    wire_capture=wire_capture
                )
    elif wire_capture is not None:
        # Update wire capture if provided (outside lock - safe assignment)
        _wire_capture_coordinator = WireCaptureCoordinator(wire_capture=wire_capture)
    return _wire_capture_coordinator


def _normalize_usage_to_summary(usage: Any) -> UsageSummary | None:
    """Normalize usage to UsageSummary contract for boundary safety.

    Args:
        usage: UsageSummary instance, dict[str, Any], or None

    Returns:
        UsageSummary instance or None
    """
    if usage is None:
        return None
    if isinstance(usage, UsageSummary):
        return usage
    if isinstance(usage, dict):
        return UsageSummary.from_dict(usage)
    # Fallback: try to convert to dict if it has dict-like interface
    if hasattr(usage, "get"):
        return UsageSummary.from_dict(dict(usage))  # type: ignore[arg-type]
    return None


def _normalize_metadata_to_json_safe(metadata: Any) -> dict[str, JsonValue] | None:
    """Normalize metadata to JSON-safe dict[str, JsonValue] for boundary safety.

    Args:
        metadata: dict[str, JsonValue], dict[str, Any], or None

    Returns:
        dict[str, JsonValue] or None
    """
    if metadata is None:
        return None
    if isinstance(metadata, dict):
        # Sanitize to ensure all values are JSON-serializable
        sanitized = sanitize_dict_for_json(metadata)
        # Type narrowing: sanitize_dict_for_json returns dict[str, Any] but
        # we know it's JSON-safe, so we can safely cast to dict[str, JsonValue]
        return sanitized  # type: ignore[return-value]
    # Fallback: try to convert to dict if it has dict-like interface
    if hasattr(metadata, "items"):
        sanitized = sanitize_dict_for_json(dict(metadata))  # type: ignore[arg-type]
        return sanitized  # type: ignore[return-value]
    return None


def _normalize_response_envelope(
    domain_response: (
        ResponseEnvelope
        | StreamingResponseEnvelope
        | ProcessedResponse
        | ChatResponse
        | dict[str, Any]
        | Any
    ),
) -> ResponseEnvelope:
    """Normalize various response types to ResponseEnvelope.

    Ensures usage is normalized to UsageSummary | None and metadata is normalized
    to dict[str, JsonValue] | None for boundary safety (Requirement 2.4, 6.1, 6.2).
    """
    if isinstance(domain_response, ResponseEnvelope):
        # Already a ResponseEnvelope - ensure usage and metadata are normalized
        return ResponseEnvelope(
            content=domain_response.content,
            headers=domain_response.headers,
            status_code=domain_response.status_code,
            media_type=domain_response.media_type,
            usage=_normalize_usage_to_summary(domain_response.usage),
            metadata=_normalize_metadata_to_json_safe(domain_response.metadata),
            canonical_usage=domain_response.canonical_usage,
        )
    elif isinstance(domain_response, ChatResponse):
        # ChatResponse already has typed usage: UsageSummary | None
        # Normalize metadata to JSON-safe
        chat_metadata: dict[str, JsonValue] | None = None
        if domain_response.model:
            chat_metadata = _normalize_metadata_to_json_safe(
                {"model": domain_response.model}
            )
        return ResponseEnvelope(
            content=domain_response.model_dump(),
            headers=None,
            status_code=200,
            usage=_normalize_usage_to_summary(domain_response.usage),
            metadata=chat_metadata,
        )
    elif isinstance(domain_response, ProcessedResponse):
        # ProcessedResponse already has typed usage and metadata, but normalize to ensure consistency
        return ResponseEnvelope(
            content=domain_response.content,
            headers=None,
            status_code=200,
            usage=_normalize_usage_to_summary(domain_response.usage),
            metadata=_normalize_metadata_to_json_safe(domain_response.metadata),
        )
    elif isinstance(domain_response, dict):
        # Extract usage and metadata from dict if present
        dict_usage: UsageSummary | None = None
        dict_metadata: dict[str, JsonValue] | None = None
        if "usage" in domain_response:
            dict_usage = _normalize_usage_to_summary(domain_response["usage"])
        if "metadata" in domain_response:
            dict_metadata = _normalize_metadata_to_json_safe(
                domain_response["metadata"]
            )
        return ResponseEnvelope(
            content=domain_response,
            headers=None,
            status_code=200,
            usage=dict_usage,
            metadata=dict_metadata,
        )
    else:
        # Handle StreamingResponseEnvelope or other types
        other_usage: UsageSummary | None = None
        other_metadata: dict[str, JsonValue] | None = None
        if hasattr(domain_response, "usage"):
            other_usage = _normalize_usage_to_summary(
                getattr(domain_response, "usage", None)
            )
        if hasattr(domain_response, "metadata"):
            other_metadata = _normalize_metadata_to_json_safe(
                getattr(domain_response, "metadata", None)
            )
        if hasattr(domain_response, "model_dump"):
            content_dict = domain_response.model_dump()  # type: ignore[attr-defined]
            return ResponseEnvelope(
                content=(
                    content_dict
                    if isinstance(content_dict, dict)
                    else str(domain_response)
                ),
                headers=None,
                status_code=200,
                usage=other_usage,
                metadata=other_metadata,
            )
        return ResponseEnvelope(
            content=str(domain_response),
            headers=None,
            status_code=200,
            usage=other_usage,
            metadata=other_metadata,
        )  # type: ignore[arg-type]


def _apply_content_converter(
    content: Any, converter: Callable[[Any], Any] | None
) -> Any:
    """Apply content converter if provided."""
    if converter:
        return converter(content)
    return content


async def _string_to_async_iterator(content: bytes) -> AsyncIterator[ProcessedResponse]:
    """Convert a bytes object to an async iterator that yields the content once."""
    yield ProcessedResponse(content=content.decode("utf-8"))


def _chunk_signals_done(content: Any, metadata: dict[str, Any] | None) -> bool:
    """Detect if a streaming chunk signals end-of-stream.

    This function is kept here because it's imported by content_converter.py.
    """

    def _has_meaningful_payload(payload: Any) -> bool:
        """Check whether a chunk carries assistant content, tool calls, or usage."""
        if payload is None:
            return False

        if isinstance(payload, dict):
            usage_block = payload.get("usage")
            if isinstance(usage_block, dict):
                return True

            choices: list[Any] = payload.get("choices", [])  # type: ignore[assignment]
            if isinstance(choices, list) and choices:
                first_choice: dict[str, Any] = choices[0]
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

    # Check for finish_reason in content (OpenAI-style chunks)
    if isinstance(content, dict):
        finish_reason = content.get("finish_reason")
        if finish_reason:
            return True

        # Check finish_reason in choices
        choices = content.get("choices")
        if isinstance(choices, list) and choices:
            for choice in choices:  # type: ignore[reportUnknownVariableType]
                if isinstance(choice, dict):
                    choice_finish = choice.get("finish_reason")
                    if choice_finish:
                        return True

    # Treat explicit terminal events as done only when the chunk is otherwise empty
    return normalized_event in {
        "message.done",
        "completion",
        "done",
    } and not _has_meaningful_payload(content)


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
        wire_capture: Optional wire capture instance
        context: Optional request context

    Returns:
        A FastAPI response
    """
    envelope = _normalize_response_envelope(domain_response)

    # Apply content converter if provided (legacy support)
    if content_converter:
        converted_content = _apply_content_converter(
            envelope.content, content_converter
        )
        envelope = ResponseEnvelope(
            content=converted_content,
            headers=envelope.headers,
            status_code=envelope.status_code,
            media_type=envelope.media_type,
            usage=envelope.usage,
            metadata=envelope.metadata,
            canonical_usage=envelope.canonical_usage,
        )

    # Determine media type
    media_type = getattr(envelope, "media_type", "application/json")

    # Build appropriate response
    response: Response
    if media_type and media_type.startswith("application/json"):
        response = _get_json_builder().build(envelope, context=context)
    else:
        response = _get_other_builder().build(envelope)
    # Capture exact emitted payload bytes for non-streaming responses.
    response_body = getattr(response, "body", b"")
    if isinstance(response_body, memoryview):
        response_body = response_body.tobytes()
    if not isinstance(response_body, bytes):
        response_body = bytes(response_body)
    response_content = response_body

    # Schedule wire capture for non-streaming responses
    if wire_capture:
        coordinator = _get_wire_capture_coordinator(wire_capture)
        coordinator.schedule_capture(envelope, response_content, context=context)

    echo_header = _resolve_b2bua_echo_header(context)
    if echo_header is not None:
        header_name, a_session_id = echo_header
        response.headers[header_name] = a_session_id

    return response


def to_fastapi_streaming_response(
    domain_response: StreamingResponseEnvelope,
    *,
    wire_capture: IWireCapture | None = None,
    context: RequestContext | None = None,
    yield_interval: int = 100,
) -> StreamingResponse:
    """Convert a domain streaming response envelope to a FastAPI streaming response.

    This function uses StreamingContentConverter and SSEAssembler to convert
    raw stream chunks to SSE format.

    XML Leakage Prevention:
    -----------------------
    This function prevents XML tool tag leakage by using ToolBlockBuffer within
    StreamingContentConverter. The buffer tracks detected tool tags dynamically
    via the streaming context registry (tracked_tags), ensuring multiline XML
    tool blocks are buffered until complete before emission. This prevents
    partial tool tags from leaking to clients. The sanitize_multiline_tool_blocks
    method in StreamingContentConverter handles the actual buffering logic via
    _apply_tag_buffer operations that hold partial tags until completion.

    Args:
        domain_response: The domain streaming response envelope
        wire_capture: Optional wire capture instance
        context: Optional request context
        yield_interval: Optional yield interval (overrides global config)

    Returns:
        A FastAPI streaming response
    """
    from src.core.domain.client_termination import ClientTerminationReason

    # Resolve yield interval from config if using default
    if yield_interval == 100:
        config_to_use: Any | None = None
        if context is not None:
            # Try to get config from app state if available
            try:
                # Use DI to get IApplicationState service instead of direct context.app_state access
                from src.core.di.services import get_service_provider
                from src.core.interfaces.application_state_interface import (
                    IApplicationState,
                )

                provider = get_service_provider()
                app_state_svc = provider.get_service(IApplicationState)  # type: ignore[type-abstract]
                if app_state_svc and hasattr(app_state_svc, "app_config"):
                    config_to_use = app_state_svc.app_config
            except (ImportError, RuntimeError, AttributeError):
                # Fallback to direct access if DI not initialized or service not found
                # Note: The linter prefers service access, but some tests may not have DI.
                # Use a safer getattr access to satisfy basic patterns
                app_state_legacy = getattr(context, "app_state", None)
                if app_state_legacy:
                    config_to_use = getattr(app_state_legacy, "config", None)

        if config_to_use:
            val = getattr(config_to_use, "streaming_yield_interval", 100)
            if isinstance(val, int):
                yield_interval = val

    envelope_metadata: dict[str, JsonValue] = (
        domain_response.metadata if isinstance(domain_response.metadata, dict) else {}
    )
    request_id: str | None = None
    if context is not None:
        rid = getattr(context, "request_id", None)
        if rid is not None:
            request_id = str(rid)
    disconnect_cleanup_scheduled = False

    content_iter = domain_response.content
    if content_iter is None:
        # Create empty iterator if content is None
        async def _empty_streamer() -> AsyncIterator[bytes]:
            # Async generator that emits no bytes; guarded yield keeps this a generator
            # without a `return` + dead `yield` pattern (static analyzers, vulture).
            if _never_emit_stream_bytes():
                yield b""  # pragma: no cover

        # Inject canonical usage headers if available (Requirement 5.5)
        # Note: StreamingResponseEnvelope doesn't have a usage field, only canonical_usage
        empty_headers = domain_response.headers or {}
        header_injector = _get_usage_header_injector()
        empty_headers = header_injector.inject_headers(
            empty_headers, {}, canonical_usage=domain_response.canonical_usage
        )
        empty_headers = _apply_b2bua_echo_header(empty_headers, context)

        return StreamingResponse(
            content=_empty_streamer(),
            media_type=getattr(domain_response, "media_type", "text/event-stream"),
            status_code=domain_response.status_code or 200,
            headers=empty_headers,
        )

    # Convert raw stream to StreamingContent using StreamingContentConverter
    converter = _get_content_converter(yield_interval=yield_interval)
    # Context dict contains RequestContext for usage recalculation.
    # Protocol allows RequestContext | None in context dict for this purpose.
    conversion_context: dict[str, JsonValue | RequestContext | None] = {
        "envelope_metadata": envelope_metadata,
        "context": context,
    }

    async def _convert_and_assemble() -> AsyncIterator[bytes]:
        """Convert raw stream to SSE bytes."""

        def _schedule_client_disconnect_cleanup(
            reason: ClientTerminationReason,
            *,
            cancel_reason: str,
            details: str,
        ) -> None:
            nonlocal disconnect_cleanup_scheduled
            if disconnect_cleanup_scheduled:
                return
            disconnect_cleanup_scheduled = True
            _schedule_disconnect_cleanup(
                lambda: _handle_client_stream_disconnect(
                    domain_response=domain_response,
                    context=context,
                    request_id=request_id,
                    cancel_reason=cancel_reason,
                    details=details,
                    termination_reason=reason,
                ),
                request_id=request_id,
            )

        # Ensure async iterator of ProcessedResponse
        # Normalize raw bytes/str to ProcessedResponse so the converter always receives
        # typed chunks (tests and legacy callers may pass raw content iterators).
        def _normalize_chunk(item: Any) -> ProcessedResponse:
            if isinstance(item, ProcessedResponse):
                return item
            return ProcessedResponse(content=item if item is not None else "")

        async def _ensure_async_iterator(
            source: AsyncIterator[ProcessedResponse] | Any,
        ) -> AsyncIterator[ProcessedResponse]:
            try:
                if hasattr(source, "__aiter__"):
                    async for item in source:  # type: ignore[async-for]
                        yield _normalize_chunk(item)
                elif hasattr(source, "__iter__"):
                    # Handle sync iterables (backward compatibility)
                    for item in source:  # type: ignore[union-attr]
                        yield _normalize_chunk(item)
                else:
                    # Not iterable - treat as single item or raise error
                    # This handles Mock objects and other non-iterable types
                    raise TypeError(
                        f"Content must be an async iterator, sync iterator, or iterable, "
                        f"got {type(source).__name__}"
                    )
            except GeneratorExit:
                # Close the source iterator if it supports aclose
                _schedule_stream_close(
                    source,
                    name="source_iter",
                    request_id=request_id,
                )
                raise
            except asyncio.CancelledError:
                _schedule_stream_close(
                    source,
                    name="source_iter",
                    request_id=request_id,
                )
                raise

        async_stream = _ensure_async_iterator(content_iter)

        # Convert to StreamingContent (async generator returns iterator directly)
        streaming_content_iter = converter.convert_stream(
            async_stream, conversion_context
        )

        # Convert StreamingContent to SSE bytes
        assembler = _get_sse_assembler(yield_interval=yield_interval)
        sse_bytes_iter = assembler.assemble_stream(streaming_content_iter, format="sse")

        # Wrap stream for wire capture if enabled
        if wire_capture:
            coordinator = _get_wire_capture_coordinator(wire_capture)
            sse_bytes_iter = coordinator.wrap_stream(
                domain_response,
                sse_bytes_iter,
                context=context,
            )

        # Counter for chunk-based yielding to event loop
        chunk_count = 0
        try:
            async for sse_chunk in sse_bytes_iter:
                chunk_count += 1
                yield sse_chunk

                # Yield to event loop periodically to maintain responsiveness
                if chunk_count % yield_interval == 0:
                    await asyncio.sleep(0)
        except GeneratorExit:
            # Client disconnected - cancel backend work and clean up iterators.
            _schedule_client_disconnect_cleanup(
                ClientTerminationReason.CLIENT_DISCONNECTED,
                cancel_reason="client_disconnect",
                details="fastapi_stream_generator_exit",
            )
            _schedule_stream_close(
                sse_bytes_iter,
                name="sse_bytes_iter",
                request_id=request_id,
            )
            raise
        except asyncio.CancelledError:
            # Request cancelled by transport/runtime - trigger same cleanup path.
            _schedule_client_disconnect_cleanup(
                ClientTerminationReason.CLIENT_CANCELLED,
                cancel_reason="stream_cancelled",
                details="fastapi_stream_cancelled_error",
            )
            _schedule_stream_close(
                sse_bytes_iter,
                name="sse_bytes_iter",
                request_id=request_id,
            )
            raise

    # Inject canonical usage headers if available (Requirement 5.5)
    # Note: StreamingResponseEnvelope doesn't have a usage field, only canonical_usage
    headers = domain_response.headers or {}
    header_injector = _get_usage_header_injector()
    headers = header_injector.inject_headers(
        headers, {}, canonical_usage=domain_response.canonical_usage
    )
    headers = _apply_b2bua_echo_header(headers, context)

    # Build streaming response
    return StreamingResponse(
        content=_convert_and_assemble(),
        media_type=getattr(domain_response, "media_type", "text/event-stream"),
        status_code=domain_response.status_code or 200,
        headers=headers,
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
        wire_capture: Optional wire capture instance
        context: Optional request context

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


# Backward compatibility wrappers for test helpers
def _inject_reasoning_metadata(
    content: Any,
    metadata: dict[str, Any] | None,
    streaming: bool = False,
) -> Any:
    """Inject reasoning metadata into content (backward compatibility wrapper).

    This function is kept for backward compatibility with tests.
    It delegates to ReasoningInjector.
    """
    from src.core.transport.fastapi.adapters.metadata.reasoning_injector import (
        ReasoningInjector,
    )

    injector = ReasoningInjector()
    return injector.inject_reasoning(content, metadata or {}, streaming=streaming)


def _normalize_content(content: Any) -> Any:
    """Normalize content for processing (backward compatibility wrapper).

    This function is kept for backward compatibility with tests.
    It delegates to ReasoningInjector's internal normalization.
    """
    from src.core.transport.fastapi.adapters.metadata.reasoning_injector import (
        ReasoningInjector,
    )

    injector = ReasoningInjector()
    # Access the private method via the instance
    return injector._normalize_content(content)  # type: ignore[attr-defined]


def _format_chunk_as_sse(content: dict[str, Any] | bytes | str) -> bytes:
    """Format content as SSE bytes (backward compatibility wrapper).

    This function is kept for backward compatibility with tests.
    It delegates to SSEFormatter.format_chunk().

    Args:
        content: Content to format (dict, bytes, or str)

    Returns:
        SSE-formatted bytes
    """
    from src.core.transport.fastapi.adapters.sse.formatter import SSEFormatter

    formatter = SSEFormatter()
    return formatter.format_chunk(content)


def _build_streaming_payload(
    content: Any,
    metadata: dict[str, Any],
    reasoning_text: str | None,
    *,
    streaming: bool = True,
) -> dict[str, Any]:
    """Build OpenAI-style payload when content is not dict (backward compatibility wrapper).

    This function is kept for backward compatibility with tests.
    It delegates to ReasoningInjector.build_streaming_payload().

    Args:
        content: Non-dict content
        metadata: Metadata to include in payload
        reasoning_text: Optional reasoning text (extracted from metadata if None)
        streaming: Whether this is a streaming payload

    Returns:
        OpenAI-style dict payload
    """
    from src.core.transport.fastapi.adapters.metadata.reasoning_injector import (
        ReasoningInjector,
    )

    injector = ReasoningInjector()
    # If reasoning_text is provided, add it to metadata
    if reasoning_text and "reasoning_content" not in metadata:
        metadata = {**metadata, "reasoning_content": reasoning_text}
    # Use the public method which handles reasoning_text extraction
    return injector.build_streaming_payload(content, metadata, streaming=streaming)


__all__ = [
    "to_fastapi_response",
    "to_fastapi_streaming_response",
    "domain_response_to_fastapi",
    "_chunk_signals_done",  # Exported for content_converter.py
    "_inject_reasoning_metadata",  # Exported for tests
    "_normalize_content",  # Exported for tests
    "_format_chunk_as_sse",  # Exported for tests
    "_build_streaming_payload",  # Exported for tests
    "_apply_usage_headers",  # Exported for tests (property tests)
]
