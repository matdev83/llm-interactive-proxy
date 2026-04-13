"""Boundary adapter: canonical handle to legacy streaming / blocking envelopes."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from pydantic.types import JsonValue

from src.core.domain.backend_request_manager.canonical_post_backend_response import (
    CanonicalResponseHandle,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import (
    ProcessedChunkContent,
    ProcessedResponse,
)
from src.core.services.response_metadata_serialization import (
    filter_json_serializable_client_metadata,
)


def _is_terminal_stream_marker(content: object) -> bool:
    """Return True when chunk content represents terminal stream bookkeeping."""
    if content is None:
        return True

    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8", errors="ignore").strip()
        except Exception:
            return False
        return text in {"[DONE]", "data: [DONE]", "data:[DONE]", "null", ""}

    if isinstance(content, str):
        text = content.strip()
        return text in {"[DONE]", "data: [DONE]", "data:[DONE]", "null", ""}

    if isinstance(content, dict):
        if set(content.keys()) <= {"usage"}:
            return True

        choices = content.get("choices")
        if not isinstance(choices, list) or not choices:
            return False

        first = choices[0]
        if not isinstance(first, dict):
            return False

        finish_reason = first.get("finish_reason")
        delta = first.get("delta")
        message = first.get("message")

        has_user_payload = False
        if isinstance(delta, dict):
            has_user_payload = bool(delta.get("content") or delta.get("tool_calls"))
        if isinstance(message, dict):
            has_user_payload = has_user_payload or bool(
                message.get("content") or message.get("tool_calls")
            )

        return (
            isinstance(finish_reason, str)
            and finish_reason in {"stop", "length", "tool_calls", "error", "cancelled"}
            and not has_user_payload
            and not content.get("error")
        )

    return False


def _extract_sse_data_payloads(content: object) -> list[ProcessedChunkContent] | None:
    """Decode SSE ``data:`` events into non-SSE payloads.

    Returns ``None`` if input is not SSE-framed data.
    """
    if isinstance(content, bytes):
        text = content.decode("utf-8", errors="ignore")
    elif isinstance(content, str):
        text = content
    else:
        return None

    lines = text.splitlines()
    if not any(line.lstrip().startswith("data:") for line in lines):
        return None

    payloads: list[ProcessedChunkContent] = []
    event_data_lines: list[str] = []

    def _append_payload(raw_payload: str) -> None:
        payload = raw_payload.strip()
        if payload in {"", "[DONE]", "null"}:
            return

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            payloads.append(payload)
            return

        if isinstance(parsed, dict):
            payloads.append(parsed)
            return
        if isinstance(parsed, str):
            payloads.append(parsed)
            return

        payloads.append(json.dumps(parsed, separators=(",", ":")))

    def _flush_event() -> None:
        if not event_data_lines:
            return
        _append_payload("\n".join(event_data_lines))
        event_data_lines.clear()

    for line in lines:
        stripped = line.strip("\r")
        if not stripped:
            _flush_event()
            continue

        normalized = stripped.lstrip()
        if normalized.startswith(":"):
            continue

        if normalized.startswith("data:"):
            data_part = normalized[5:]
            if data_part.startswith(" "):
                data_part = data_part[1:]
            event_data_lines.append(data_part)

    _flush_event()
    return payloads


class EnvelopeCompatibilityAdapter:
    """Converts :class:`CanonicalResponseHandle` to public manager envelopes.

    Requested streaming vs non-streaming is decided only by the entrypoint
    calling ``to_streaming`` or ``to_non_streaming`` (manager boundary).
    """

    async def to_streaming(
        self,
        handle: CanonicalResponseHandle,
        context: RequestContext,
    ) -> StreamingResponseEnvelope:
        # Context reserved for future transport-context adaptation (e.g., client
        # capability negotiation, compression hints). Keeping the parameter ensures
        # interface stability when those features are added.
        del context

        content_iter = handle.stream

        async def _replay() -> AsyncIterator[ProcessedResponse]:
            async for item in content_iter:
                yield item

        return StreamingResponseEnvelope(
            content=_replay(),
            media_type=handle.media_type,
            headers=handle.headers,
            status_code=handle.status_code,
            cancel_callback=handle.cancel_callback,
            metadata=dict(handle.metadata),
            canonical_usage=handle.canonical_usage,
        )

    async def to_non_streaming(
        self,
        handle: CanonicalResponseHandle,
        context: RequestContext,
    ) -> ResponseEnvelope:
        # Context reserved for future transport-context adaptation (e.g., client
        # capability negotiation, compression hints). Keeping the parameter ensures
        # interface stability when those features are added.
        del context
        merged_metadata: dict[str, JsonValue] = dict(handle.metadata)
        usage = handle.usage

        # Accumulate meaningful chunks so non-streaming clients receive the full
        # payload when canonical backends stream token-by-token.
        chunk_count = 0
        first_content: ProcessedChunkContent = None
        last_content: ProcessedChunkContent = None
        meaningful_contents: list[ProcessedChunkContent] = []

        async for chunk in handle.stream:
            if chunk.usage is not None:
                usage = chunk.usage
            if chunk.metadata:
                merged_metadata.update(chunk.metadata)

            if chunk_count == 0:
                first_content = chunk.content
            last_content = chunk.content
            chunk_count += 1

            decoded_sse_payloads = _extract_sse_data_payloads(chunk.content)
            if decoded_sse_payloads is not None:
                meaningful_contents.extend(decoded_sse_payloads)
                continue

            if not _is_terminal_stream_marker(chunk.content):
                meaningful_contents.append(chunk.content)

        body: ProcessedChunkContent

        # Body selection priority:
        # 1. Reassembled meaningful stream payload when available
        # 2. First content if only one chunk
        # 3. Last content as fallback
        if meaningful_contents:
            if len(meaningful_contents) == 1:
                body = meaningful_contents[0]
            elif all(isinstance(item, str) for item in meaningful_contents):
                body = "".join(
                    item for item in meaningful_contents if isinstance(item, str)
                )
            elif all(isinstance(item, bytes) for item in meaningful_contents):
                body = b"".join(
                    item for item in meaningful_contents if isinstance(item, bytes)
                )
            else:
                # Preserve historical behavior for non-text streamed payloads.
                body = meaningful_contents[-1]
        elif chunk_count == 0:
            body = None
        elif chunk_count == 1:
            body = first_content
        else:
            body = last_content

        filtered_metadata = filter_json_serializable_client_metadata(
            dict(merged_metadata)
        )

        return ResponseEnvelope(
            content=body,
            headers=handle.headers,
            status_code=handle.status_code,
            media_type=handle.media_type,
            usage=usage,
            metadata=filtered_metadata or None,
            canonical_usage=handle.canonical_usage,
        )
