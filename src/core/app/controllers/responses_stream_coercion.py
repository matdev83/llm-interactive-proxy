"""Coercion helpers for Responses streaming chunks into canonical dict payloads."""

from __future__ import annotations

import json
from typing import Any, cast

from src.core.interfaces.response_processor_interface import ProcessedResponse


def coerce_stream_chunk_payload(
    chunk: Any, *, default_response_id: str
) -> dict[str, Any] | None:
    """Normalize stream iterator items into a domain-style chunk dict."""

    def _parse_json_dict(raw: bytes | bytearray | str) -> dict[str, Any] | None:
        try:
            text = (
                bytes(raw).decode("utf-8")
                if isinstance(raw, bytes | bytearray)
                else raw
            )
            parsed = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None

    if isinstance(chunk, bytes | bytearray | str):
        return _parse_json_dict(chunk)

    if isinstance(chunk, ProcessedResponse):
        if isinstance(chunk.content, dict):
            return chunk.content
        if isinstance(chunk.content, bytes | bytearray | str):
            parsed_content = _parse_json_dict(chunk.content)
            if parsed_content is not None:
                return parsed_content
        md = chunk.metadata or {}
        if md.get("tool_calls"):
            return {
                "id": md.get("id", default_response_id),
                "model": md.get("model", "unknown"),
                "created": md.get("created"),
                "choices": [
                    {
                        "index": 0,
                        "delta": {"tool_calls": md["tool_calls"]},
                        "finish_reason": md.get("finish_reason"),
                    }
                ],
            }
        if md.get("is_done") or md.get("finish_reason"):
            return {
                "id": md.get("id", default_response_id),
                "model": md.get("model", "unknown"),
                "created": md.get("created"),
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": md.get("finish_reason", "stop"),
                    },
                ],
            }
        return None

    if isinstance(chunk, dict):
        return chunk
    if hasattr(chunk, "content"):
        content = getattr(chunk, "content", None)
        if isinstance(content, dict):
            return cast(dict[str, Any], content)
        if isinstance(content, bytes | bytearray | str):
            return _parse_json_dict(content)
    return None
