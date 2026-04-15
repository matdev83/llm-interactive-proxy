"""Capture entry metadata helpers and header validation."""

from __future__ import annotations

from typing import Any

from src.core.wire_capture.inspection.constants import (
    CAPTURE_MAGIC,
    CAPTURE_VERSION,
    META_FIELD_NAMES,
)


def validate_capture_header(header: Any) -> None:
    """Reject unsupported capture file headers before reading entries."""
    if not isinstance(header, dict):
        raise ValueError(
            f"Unsupported capture file header type: {type(header).__name__}"
        )

    magic = header.get("magic")
    if magic != CAPTURE_MAGIC:
        raise ValueError(
            f"Unsupported capture file magic: {magic!r} (expected {CAPTURE_MAGIC!r})"
        )

    version = header.get("version")
    if version != CAPTURE_VERSION:
        raise ValueError(
            f"Unsupported capture file version: {version!r} "
            f"(expected {CAPTURE_VERSION})"
        )


def meta_a_session_id(meta: dict[str, Any]) -> str | None:
    """Return A-leg session id with backward-compatible fallback to sid."""
    a_session_id = meta.get("asid")
    if isinstance(a_session_id, str) and a_session_id:
        return a_session_id
    legacy_session_id = meta.get("sid")
    if isinstance(legacy_session_id, str) and legacy_session_id:
        return legacy_session_id
    return None


def meta_b_session_id(meta: dict[str, Any]) -> str | None:
    """Return B-leg session id when present."""
    b_session_id = meta.get("bsid")
    if isinstance(b_session_id, str) and b_session_id:
        return b_session_id
    return None


def meta_is_stream_start(meta: dict[str, Any]) -> bool:
    """Return True when metadata marks a stream start marker."""
    return bool(meta.get("ss"))


def meta_is_stream_end(meta: dict[str, Any]) -> bool:
    """Return True when metadata marks a stream end marker."""
    return bool(meta.get("se"))


def meta_http_status(meta: dict[str, Any]) -> int | None:
    """Return best-effort HTTP status for legacy and V2 captures."""
    status = meta.get("http_status")
    if isinstance(status, int):
        return status
    if isinstance(status, float) and status.is_integer():
        return int(status)

    status = meta.get("sc")
    if isinstance(status, int):
        return status
    if isinstance(status, float) and status.is_integer():
        return int(status)
    return None


def normalize_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Expand compact CBOR metadata keys into user-facing names."""
    normalized: dict[str, Any] = {}
    for key, value in meta.items():
        normalized[META_FIELD_NAMES.get(key, key)] = value
    return normalized


def meta_request_id(meta: dict[str, Any]) -> str | None:
    """Return request id when present."""
    request_id = meta.get("rid")
    if isinstance(request_id, str) and request_id:
        return request_id
    return None
