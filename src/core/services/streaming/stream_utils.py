from __future__ import annotations

"""Utility helpers for streaming response processors."""

from typing import Any
from uuid import uuid4
import threading

from src.core.ports.streaming import StreamingContent

_UNIQUE_METADATA_KEYS = (
    "stream_id",
    "request_id",
    "response_id",
    "id",
    "chunk_id",
    "event_id",
)

_StreamKey = tuple[str | None, str | None, str | None]

_fallback_lock = threading.Lock()
_active_stream_ids: dict[_StreamKey, str] = {}
_reverse_stream_keys: dict[str, _StreamKey] = {}


def _normalize_component(value: Any) -> str | None:
    """Normalize arbitrary metadata values to comparable strings."""

    if value is None:
        return None
    try:
        text = str(value)
    except Exception:
        return None
    return text or None


def _build_fallback_key(metadata: dict[str, Any]) -> _StreamKey:
    """Construct a key used when explicit stream identifiers are missing."""

    request_component = _normalize_component(
        metadata.get("request_id") or metadata.get("response_id")
    )
    id_component = _normalize_component(
        metadata.get("id")
        or metadata.get("chunk_id")
        or metadata.get("event_id")
    )
    session_component = _normalize_component(metadata.get("session_id"))
    return (request_component, id_component, session_component)


def get_stream_id(content: StreamingContent) -> str:
    """Return a stable identifier for the current stream.

    Processors rely on this value to keep per-stream buffers isolated. The
    identifier is sourced from the chunk metadata when available. If the
    upstream pipeline has not yet assigned one, a new UUID is generated and
    stored back into the metadata so that subsequent processors can reuse it.

    When multiple streaming responses share the same session identifier (for
    example, parallel requests from the same client), we prefer more specific
    metadata such as request IDs so that each stream remains isolated.
    """

    metadata = content.metadata
    raw_stream_id = metadata.get("stream_id")
    stream_id: str | None = _normalize_component(raw_stream_id)

    if stream_id is None:
        for key in _UNIQUE_METADATA_KEYS[1:]:
            candidate = _normalize_component(metadata.get(key))
            if candidate:
                stream_id = candidate
                break

    if stream_id is None:
        fallback_key = _build_fallback_key(metadata)
        if fallback_key != (None, None, None):
            with _fallback_lock:
                stream_id = _active_stream_ids.get(fallback_key)
                if stream_id is None:
                    stream_id = uuid4().hex
                    _active_stream_ids[fallback_key] = stream_id
                    _reverse_stream_keys[stream_id] = fallback_key
        else:
            stream_id = uuid4().hex

    metadata["stream_id"] = stream_id

    if content.is_done or content.is_cancellation:
        with _fallback_lock:
            fallback_key = _reverse_stream_keys.pop(stream_id, None)
            if fallback_key is not None:
                _active_stream_ids.pop(fallback_key, None)

    return stream_id
