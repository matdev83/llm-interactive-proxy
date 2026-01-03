from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParsedResponsesStreamChunk:
    chunk: dict[str, Any] | None
    event_type_from_sse: str | None = None
    error: dict[str, Any] | None = None


def parse_responses_stream_chunk(chunk: Any) -> ParsedResponsesStreamChunk:
    import time
    import uuid

    def _heartbeat_chunk(finish_reason: str | None = None) -> dict[str, Any]:
        return {
            "id": f"resp-{uuid.uuid4().hex[:16]}",
            "object": "response.chunk",
            "created": int(time.time()),
            "model": "unknown",
            "choices": [
                {"index": 0, "delta": {}, "finish_reason": finish_reason},
            ],
        }

    if isinstance(chunk, bytes | bytearray):
        try:
            chunk = chunk.decode("utf-8")
        except UnicodeDecodeError:
            return ParsedResponsesStreamChunk(
                chunk=None,
                error={"error": "Invalid chunk format: unable to decode bytes"},
            )

    event_type_from_sse: str | None = None
    if isinstance(chunk, str):
        stripped_chunk = chunk.strip()

        if not stripped_chunk:
            return ParsedResponsesStreamChunk(
                chunk=None,
                error={"error": "Invalid chunk format: empty string"},
            )

        if stripped_chunk.startswith(":"):
            return ParsedResponsesStreamChunk(chunk=_heartbeat_chunk())

        data_parts: list[str] = []
        has_data_prefix = False
        for raw_line in chunk.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(":"):
                return ParsedResponsesStreamChunk(chunk=_heartbeat_chunk())
            if line.startswith("event:"):
                event_type_from_sse = line[6:].strip()
                continue
            if line.startswith("data:"):
                has_data_prefix = True
                payload = line[5:].strip()
                if payload.startswith("event:") and not event_type_from_sse:
                    event_type_from_sse = payload[6:].strip()
                    continue
                data_parts.append(payload)
                continue
            data_parts.append(line)

        stripped_chunk = "\n".join(part for part in data_parts if part).strip()

        if not has_data_prefix:
            return ParsedResponsesStreamChunk(chunk=_heartbeat_chunk())

        if not stripped_chunk:
            return ParsedResponsesStreamChunk(chunk=_heartbeat_chunk())

        if stripped_chunk == "[DONE]":
            return ParsedResponsesStreamChunk(
                chunk=_heartbeat_chunk(finish_reason="stop")
            )

        try:
            chunk = json.loads(stripped_chunk)
        except json.JSONDecodeError as exc:
            logger.warning(
                "Responses stream chunk JSON decode failed: %s",
                stripped_chunk[:300],
                exc_info=True,
            )
            return ParsedResponsesStreamChunk(
                chunk=None,
                event_type_from_sse=event_type_from_sse,
                error={
                    "error": "Invalid chunk format: expected JSON after 'data:' prefix",
                    "details": {"message": str(exc)},
                },
            )

    if not isinstance(chunk, dict):
        return ParsedResponsesStreamChunk(
            chunk=None,
            event_type_from_sse=event_type_from_sse,
            error={"error": "Invalid chunk format: expected a dictionary"},
        )

    return ParsedResponsesStreamChunk(
        chunk=chunk,
        event_type_from_sse=event_type_from_sse,
    )
