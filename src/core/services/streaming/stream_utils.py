from __future__ import annotations

"""Utility helpers for streaming response processors."""

from uuid import uuid4

from src.core.domain.streaming_response_processor import StreamingContent


def get_stream_id(content: StreamingContent) -> str:
    """Return a stable identifier for the current stream.

    Processors rely on this value to keep per-stream buffers isolated. The
    identifier is sourced from the chunk metadata when available. If the
    upstream pipeline has not yet assigned one, a new UUID is generated and
    stored back into the metadata so that subsequent processors can reuse it.
    """

    metadata = content.metadata
    stream_id = metadata.get("stream_id") or metadata.get("session_id") or metadata.get("id")
    if not stream_id:
        stream_id = uuid4().hex
        metadata["stream_id"] = stream_id
    return str(stream_id)

