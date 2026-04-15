#!/usr/bin/env python
"""
CBOR Wire Capture Inspection Tool

A utility script for inspecting CBOR wire capture files to analyze
client/server traffic flows, detect issues, and debug problems.

Usage:
    python scripts/inspect_cbor_capture.py <capture_file> [options]

Examples:
    # Basic inspection with summary
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor

    # List all backends in the capture file
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --list-backends

    # Show first 10 entries with full data
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --entries 10

    # Filter entries by backend
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --backend openai --entries 10

    # Analyze request/response pairs
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --analyze

    # Analyze only pairs from a specific backend
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --analyze --backend anthropic

    # Export to JSON for further processing
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --json > output.json

    # Export only entries from a specific backend to JSON
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --backend gemini --json > gemini_only.json

    # Filter by direction
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --direction backend_to_proxy

    # Combine backend and direction filters
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --backend openai --direction backend_to_proxy --entries 20

    # NEW FEATURES:
    # View last 20 entries
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --last 20

    # View specific range
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --range 80-98

    # Show context around entry
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --around 83 --context 5

    # Jump to specific entry
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --entry 83 --verbose

    # Timeline view with gaps
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --timeline --backend gemini-oauth-plan

    # Auto-detect issues
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --detect-issues

    # Show HTTP status summary from capture metadata
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --status-summary

    # Group by session
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --group-by-session

    # Track specific request
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --track-request 3 --backend gemini-oauth-plan

    # Analyze streaming performance
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --analyze-streaming --backend gemini-oauth-plan

    # Combine features
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --detect-issues --timeline --backend gemini-oauth-plan

    # Filter by time range (Unix timestamps or ISO datetime)
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --start-time 1702300000 --end-time 1702400000
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --start-time "2024-01-15T10:00:00" --end-time "2024-01-15T11:00:00"
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --start-time "10:30:00" --end-time "11:00:00" --entries 50
"""

from __future__ import annotations

import argparse
import bisect
import datetime
import json
import sys
import zlib
from pathlib import Path
from typing import Any

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import cbor2

# Direction mapping
DIRECTION_NAMES = {
    0: "CLIENT_TO_PROXY",
    1: "PROXY_TO_CLIENT",
    2: "PROXY_TO_BACKEND",
    3: "BACKEND_TO_PROXY",
}

DIRECTION_SYMBOLS = {
    0: "C->P",  # Client to Proxy
    1: "P->C",  # Proxy to Client
    2: "P->B",  # Proxy to Backend
    3: "B->P",  # Backend to Proxy
}

CAPTURE_MAGIC = "LLMPROXY-CAPTURE-V2"
CAPTURE_VERSION = 2

META_FIELD_NAMES = {
    "sid": "session_id",
    "asid": "a_session_id",
    "bsid": "b_session_id",
    "bseq": "b_seq",
    "be": "backend",
    "mod": "model",
    "key": "key_name",
    "host": "client_host",
    "ua": "user_agent",
    "rid": "request_id",
    "ci": "chunk_index",
    "ss": "is_stream_start",
    "se": "is_stream_end",
    "tc": "total_chunks",
    "tb": "total_bytes",
    "cu": "canonical_usage",
    "sc": "status_code",
    "ra": "retry_after_seconds",
    "rat": "retry_attempt",
    "rtry": "is_retry",
    "acct": "account_id",
    "rts": "request_timestamp",
    "pts": "response_timestamp",
    "lat": "latency_ms",
    "ttfb": "ttfb_ms",
    "sdur": "stream_duration_ms",
    "eos": "eos",
    "eos_sig": "eos_signal",
    "eos_reason": "eos_reason",
    "eos_term": "eos_termination_category",
    "eos_err_cls": "eos_error_classification",
    "eos_err_code": "eos_error_status_code",
    "wire_schema": "wire_schema",
    "transport": "transport",
    "event": "protocol_event",
    "http_method": "http_method",
    "url": "url",
    "http_status": "http_status_code",
    "http_reason": "http_reason_phrase",
    "http_version": "http_version",
    "ws_message_type": "websocket_message_type",
    "ccid": "compression_correlation_id",
    "crc": "compression_records_count",
}


def _validate_capture_header(header: Any) -> None:
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


def _meta_a_session_id(meta: dict[str, Any]) -> str | None:
    """Return A-leg session id with backward-compatible fallback to sid."""
    a_session_id = meta.get("asid")
    if isinstance(a_session_id, str) and a_session_id:
        return a_session_id
    legacy_session_id = meta.get("sid")
    if isinstance(legacy_session_id, str) and legacy_session_id:
        return legacy_session_id
    return None


def _meta_b_session_id(meta: dict[str, Any]) -> str | None:
    """Return B-leg session id when present."""
    b_session_id = meta.get("bsid")
    if isinstance(b_session_id, str) and b_session_id:
        return b_session_id
    return None


def _meta_is_stream_start(meta: dict[str, Any]) -> bool:
    """Return True when metadata marks a stream start marker."""
    return bool(meta.get("ss"))


def _meta_is_stream_end(meta: dict[str, Any]) -> bool:
    """Return True when metadata marks a stream end marker."""
    return bool(meta.get("se"))


def _meta_http_status(meta: dict[str, Any]) -> int | None:
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


def _normalize_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Expand compact CBOR metadata keys into user-facing names."""
    normalized: dict[str, Any] = {}
    for key, value in meta.items():
        normalized[META_FIELD_NAMES.get(key, key)] = value
    return normalized


def _backend_payload_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return backend entries that carry actual bytes, not stream markers."""
    result: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("dir") != 3:
            continue
        if entry.get("data"):
            result.append(entry)
    return result


def _entry_timestamp(entry: dict[str, Any]) -> float:
    """Return an entry timestamp as float with a safe fallback."""
    ts = entry.get("ts", 0)
    return float(ts) if isinstance(ts, int | float) else 0.0


def _compute_backend_ttft(
    request_entry: dict[str, Any], backend_entries: list[dict[str, Any]]
) -> float | None:
    """Compute TTFT using explicit V2 metadata when available."""
    for entry in backend_entries:
        meta = entry.get("meta", {})
        ttfb_ms = meta.get("ttfb")
        if isinstance(ttfb_ms, int | float):
            return float(ttfb_ms) / 1000.0

    payload_entries = _backend_payload_entries(backend_entries)
    if payload_entries:
        return _entry_timestamp(payload_entries[0]) - _entry_timestamp(request_entry)

    if backend_entries:
        return _entry_timestamp(backend_entries[0]) - _entry_timestamp(request_entry)

    return None


def _compute_backend_duration(
    request_entry: dict[str, Any], backend_entries: list[dict[str, Any]]
) -> float | None:
    """Compute request duration using stream-end metadata when available."""
    for entry in reversed(backend_entries):
        meta = entry.get("meta", {})
        if _meta_is_stream_end(meta):
            sdur = meta.get("sdur")
            if isinstance(sdur, int | float):
                return float(sdur) / 1000.0
            lat = meta.get("lat")
            if isinstance(lat, int | float):
                return float(lat) / 1000.0
            return _entry_timestamp(entry) - _entry_timestamp(request_entry)

    payload_entries = _backend_payload_entries(backend_entries)
    if payload_entries:
        return _entry_timestamp(payload_entries[-1]) - _entry_timestamp(request_entry)

    if backend_entries:
        return _entry_timestamp(backend_entries[-1]) - _entry_timestamp(request_entry)

    return None


def _meta_request_id(meta: dict[str, Any]) -> str | None:
    """Return request id when present."""
    request_id = meta.get("rid")
    if isinstance(request_id, str) and request_id:
        return request_id
    return None


def _cp_window_end_index(
    entries: list[dict[str, Any]], client_idx: int, client_meta: dict[str, Any]
) -> int:
    """Exclusive end index: entries belonging to the client request at client_idx.

    With B2BUA metadata, bounds to the next CLIENT_TO_PROXY on the same A-leg
    (asid or legacy sid). Without an A-leg id, the window is unbounded (caller
    correlates by request id / other heuristics).
    """
    a_sid = _meta_a_session_id(client_meta)
    if not a_sid:
        return len(entries)
    for k in range(client_idx + 1, len(entries)):
        if entries[k].get("dir") != 0:
            continue
        next_meta = entries[k].get("meta", {})
        if _meta_a_session_id(next_meta) == a_sid:
            return k
    return len(entries)


def _pb_candidates_after_cp(
    entries: list[dict[str, Any]],
    client_idx: int,
    client_meta: dict[str, Any],
) -> list[int]:
    """Indices of P->B entries that forward this client request (B2BUA-aware).

    Prefer same request id within the client window (legacy / single-leg captures).
    When no P->B shares the client rid (typical B2BUA: new rid on the B-leg), fall
    back to every PROXY_TO_BACKEND on the same A-leg session within the window.
    """
    client_rid = _meta_request_id(client_meta)
    end = _cp_window_end_index(entries, client_idx, client_meta)
    by_rid: list[int] = []
    for i in range(client_idx + 1, end):
        if entries[i].get("dir") != 2:
            continue
        if client_rid and _meta_request_id(entries[i].get("meta", {})) == client_rid:
            by_rid.append(i)
    if by_rid:
        return by_rid

    a_sid = _meta_a_session_id(client_meta)
    if not a_sid:
        return []

    result: list[int] = []
    for i in range(client_idx + 1, end):
        if entries[i].get("dir") != 2:
            continue
        if _meta_a_session_id(entries[i].get("meta", {})) == a_sid:
            result.append(i)
    return result


def _pb_has_response_by_rid(
    pb_indices_by_rid: dict[str, list[int]],
    bp_indices_by_rid: dict[str, list[int]],
    request_id: str,
    pb_idx: int,
) -> bool:
    """True when some B->P for the same rid occurs after this P->B before the next."""
    pb_list = pb_indices_by_rid.get(request_id)
    bp_list = bp_indices_by_rid.get(request_id)
    if not pb_list or not bp_list:
        return False

    pos = bisect.bisect_right(pb_list, pb_idx)
    next_pb_idx = pb_list[pos] if pos < len(pb_list) else None

    bp_pos = bisect.bisect_right(bp_list, pb_idx)
    if bp_pos >= len(bp_list):
        return False
    if next_pb_idx is None:
        return True
    return bp_list[bp_pos] < next_pb_idx


def _pb_has_response_for_pb(
    pb_indices_by_sid: dict[str, list[int]],
    bp_indices_by_sid: dict[str, list[int]],
    pb_indices_by_rid: dict[str, list[int]],
    bp_indices_by_rid: dict[str, list[int]],
    pb_meta: dict[str, Any],
    pb_idx: int,
) -> bool:
    """Whether this P->B sees a correlated B->P (rid first, then B-leg / A-leg sid)."""
    rid = _meta_request_id(pb_meta)
    if rid and _pb_has_response_by_rid(
        pb_indices_by_rid, bp_indices_by_rid, rid, pb_idx
    ):
        return True

    b_session_id = _meta_b_session_id(pb_meta)
    if (
        isinstance(b_session_id, str)
        and b_session_id
        and _pb_has_response_by_session(
            pb_indices_by_sid, bp_indices_by_sid, pb_idx, b_session_id
        )
    ):
        return True

    for session_id in _pb_candidate_session_ids(pb_meta):
        if session_id == b_session_id:
            continue
        if _pb_has_response_by_session(
            pb_indices_by_sid, bp_indices_by_sid, pb_idx, session_id
        ):
            return True
    return False


def _pb_candidate_session_ids(pb_meta: dict[str, Any]) -> list[str]:
    """Session ids carried on a P->B entry for B->P correlation (A-leg and B-leg)."""
    candidate_ids: list[str] = []
    a_session_id = _meta_a_session_id(pb_meta)
    b_session_id = _meta_b_session_id(pb_meta)
    if isinstance(a_session_id, str) and a_session_id:
        candidate_ids.append(a_session_id)
    if isinstance(b_session_id, str) and b_session_id and b_session_id != a_session_id:
        candidate_ids.append(b_session_id)
    return candidate_ids


def _pb_has_response_by_session(
    pb_indices_by_sid: dict[str, list[int]],
    bp_indices_by_sid: dict[str, list[int]],
    pb_idx: int,
    sid: str,
) -> bool:
    pb_list = pb_indices_by_sid.get(sid)
    bp_list = bp_indices_by_sid.get(sid)
    if not pb_list or not bp_list:
        return False

    pos = bisect.bisect_right(pb_list, pb_idx)
    next_pb_idx = pb_list[pos] if pos < len(pb_list) else None

    bp_pos = bisect.bisect_right(bp_list, pb_idx)
    if bp_pos >= len(bp_list):
        return False
    if next_pb_idx is None:
        return True
    return bp_list[bp_pos] < next_pb_idx


def _collect_backend_response_for_pb(
    entries: list[dict[str, Any]], pb_idx: int
) -> list[dict[str, Any]]:
    """B->P chunks for one P->B hop.

    With a B-leg session id, ends at the next PROXY_TO_BACKEND on the same bsid.
    Otherwise correlates by backend request id (rid), skipping interleaved P->B
    rows for other requests (same as global rid correlation).
    """
    pb_meta = entries[pb_idx].get("meta", {})
    b_rid = _meta_request_id(pb_meta)
    b_sid = _meta_b_session_id(pb_meta)
    chunks: list[dict[str, Any]] = []

    for j in range(pb_idx + 1, len(entries)):
        e = entries[j]
        if e.get("dir") == 0:
            break
        if e.get("dir") == 2:
            next_meta = e.get("meta", {})
            if b_sid and _meta_b_session_id(next_meta) == b_sid:
                break
            continue
        if e.get("dir") == 3:
            m = e.get("meta", {})
            if (
                b_rid
                and _meta_request_id(m) == b_rid
                or b_sid
                and _meta_b_session_id(m) == b_sid
                or not b_rid
                and not b_sid
            ):
                chunks.append(e)

    return chunks


def _collect_backend_chunks_for_cp(
    entries: list[dict[str, Any]], cp_idx: int
) -> list[dict[str, Any]]:
    """All B->P payload flow for the client request at cp_idx (rid or B2BUA window)."""
    cp_meta = entries[cp_idx].get("meta", {})
    rid = _meta_request_id(cp_meta)
    if rid:
        correlated = _collect_correlated_entries(
            entries, start_index=cp_idx, request_id=rid, direction=3
        )
        if correlated:
            return correlated

    seen_seq: set[Any] = set()
    ordered: list[dict[str, Any]] = []
    for pb_idx in _pb_candidates_after_cp(entries, cp_idx, cp_meta):
        for chunk in _collect_backend_response_for_pb(entries, pb_idx):
            seq = chunk.get("seq")
            if seq in seen_seq:
                continue
            seen_seq.add(seq)
            ordered.append(chunk)

    ordered.sort(key=lambda e: (e.get("seq", 0), _entry_timestamp(e)))
    if ordered:
        return ordered

    return _collect_correlated_entries(
        entries, start_index=cp_idx, request_id=None, direction=3
    )


def _collect_proxy_to_client_after_cp(
    entries: list[dict[str, Any]], cp_idx: int
) -> list[dict[str, Any]]:
    """P->C entries for this client request when rid correlation fails (B2BUA)."""
    cp_meta = entries[cp_idx].get("meta", {})
    a_sid = _meta_a_session_id(cp_meta)
    cp_rid = _meta_request_id(cp_meta)
    out: list[dict[str, Any]] = []

    if a_sid:
        end = _cp_window_end_index(entries, cp_idx, cp_meta)
        for j in range(cp_idx + 1, end):
            e = entries[j]
            if e.get("dir") != 1:
                continue
            em = e.get("meta", {})
            if _meta_a_session_id(em) == a_sid:
                out.append(e)
        return out

    for j in range(cp_idx + 1, len(entries)):
        e = entries[j]
        if e.get("dir") == 0:
            break
        if e.get("dir") != 1:
            continue
        if cp_rid and _meta_request_id(e.get("meta", {})) != cp_rid:
            continue
        out.append(e)
    return out


def _collect_client_chunks_for_cp(
    entries: list[dict[str, Any]], cp_idx: int
) -> list[dict[str, Any]]:
    rid = _meta_request_id(entries[cp_idx].get("meta", {}))
    correlated = _collect_correlated_entries(
        entries, start_index=cp_idx, request_id=rid, direction=1
    )
    if correlated:
        return correlated
    return _collect_proxy_to_client_after_cp(entries, cp_idx)


def _find_enclosing_cp_index(
    entries: list[dict[str, Any]], from_idx: int
) -> int | None:
    """Nearest CLIENT_TO_PROXY at or before from_idx on the same A-leg, if any."""
    meta = entries[from_idx].get("meta", {})
    a_sid = _meta_a_session_id(meta)
    for k in range(from_idx, -1, -1):
        if entries[k].get("dir") != 0:
            continue
        if not a_sid:
            return k
        if _meta_a_session_id(entries[k].get("meta", {})) == a_sid:
            return k
    return None


def _collect_correlated_entries(
    entries: list[dict[str, Any]],
    *,
    start_index: int,
    request_id: str | None,
    direction: int,
) -> list[dict[str, Any]]:
    """Collect later entries for one request, preferring request-id correlation."""
    if request_id:
        return [
            entry
            for entry in entries[start_index + 1 :]
            if entry.get("dir") == direction
            and _meta_request_id(entry.get("meta", {})) == request_id
        ]

    result: list[dict[str, Any]] = []
    for entry in entries[start_index + 1 :]:
        if entry.get("dir") == 0:
            break
        if entry.get("dir") == direction:
            result.append(entry)
    return result


def _collect_request_flow_entries(
    entries: list[dict[str, Any]],
    *,
    start_index: int,
    backend_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Collect all later entries that belong to the same request flow."""
    start_entry = entries[start_index]
    request_id = _meta_request_id(start_entry.get("meta", {}))
    if request_id:
        return [
            entry
            for entry in entries[start_index + 1 :]
            if _meta_request_id(entry.get("meta", {})) == request_id
        ]

    def _passes_backend_filter(entry: dict[str, Any], bf: str | None) -> bool:
        if bf is None:
            return True
        if bf.strip().lower() == "client":
            return entry.get("dir") in (0, 1)
        be = entry.get("meta", {}).get("be")
        return be == bf or entry.get("dir") in (0, 1)

    related: list[dict[str, Any]] = []
    req_backend = start_entry.get("meta", {}).get("be")
    for entry in entries[start_index + 1 :]:
        if entry.get("dir") == 0:
            break
        if entry.get("dir") == 2 and entry.get("meta", {}).get("be") == req_backend:
            break
        if not _passes_backend_filter(entry, backend_filter):
            continue
        related.append(entry)
    return related


def safe_decode(data: bytes, max_length: int = 200) -> str:
    """Safely decode bytes to string, handling non-ASCII."""
    if not data:
        return "(empty)"
    text = data[:max_length].decode("utf-8", errors="replace")
    # Replace non-printable characters
    result = []
    for char in text:
        if ord(char) < 32 and char not in "\n\r\t":
            result.append(f"\\x{ord(char):02x}")
        elif ord(char) >= 128:
            result.append(f"\\u{ord(char):04x}")
        else:
            result.append(char)
    return "".join(result)


def parse_all_sse_events(data: bytes) -> list[dict[str, Any]]:
    """Parse all SSE data chunks in a payload into a list of JSON objects."""
    if not data:
        return []
    text = data.decode("utf-8", errors="replace").strip()

    results = []
    # SSE format: events are separated by blank lines
    # Each event line starts with "data: "
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            json_str = line[6:].strip()
            if json_str and json_str != "[DONE]":
                try:
                    result: dict[str, Any] = json.loads(json_str)
                    results.append(result)
                except json.JSONDecodeError:
                    continue
    return results


def parse_sse_chunk(data: bytes) -> dict[str, Any] | None:
    """Legacy wrapper for backward compatibility, returns first event."""
    events = parse_all_sse_events(data)
    return events[0] if events else None


def load_capture_file(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load a CBOR capture file and return header and entries."""
    entries = []
    with open(path, "rb") as f:
        header = cbor2.load(f)
        _validate_capture_header(header)
        while True:
            try:
                entry = cbor2.load(f)
                # Handle decompression
                if entry.get("enc") == "zlib":
                    entry["data"] = zlib.decompress(entry["data"])
                    del entry["enc"]
                entries.append(entry)
            except (EOFError, cbor2.CBORDecodeEOF):
                break
            except cbor2.CBORDecodeError as e:
                # Best-effort read: some captures can contain invalid UTF-8 text items.
                # Keep the successfully decoded prefix so the inspector can still be useful.
                print(
                    f"WARNING: stopping early due to CBOR decode error after {len(entries)} entries: {e}",
                    file=sys.stderr,
                )
                break
    return header, entries


def print_summary(
    header: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    show_status_summary: bool = False,
) -> None:
    """Print a summary of the capture file."""
    print("=" * 70)
    print("CAPTURE FILE SUMMARY")
    print("=" * 70)
    print(f"Session ID: {header.get('session_id', 'N/A')}")
    print(f"Created At: {header.get('created_at', 'N/A')}")
    print(f"Total Entries: {len(entries)}")
    print()

    # Count by direction
    direction_counts: dict[int, int] = {}
    total_bytes = 0
    for e in entries:
        d = e["dir"]
        direction_counts[d] = direction_counts.get(d, 0) + 1
        total_bytes += len(e.get("data", b""))

    print("Direction Counts:")
    for d, count in sorted(direction_counts.items()):
        print(f"  {DIRECTION_NAMES.get(d, f'Unknown({d})')}: {count}")
    print(f"\nTotal Bytes: {total_bytes:,}")

    # Timing
    if len(entries) >= 2:
        first_ts = entries[0].get("ts", 0)
        last_ts = entries[-1].get("ts", 0)
        duration = last_ts - first_ts
        print(f"Duration: {duration:.2f}s")

    if show_status_summary:
        # Status codes (if present in metadata)
        status_counts: dict[int, int] = {}
        for e in entries:
            meta = e.get("meta", {})
            status = _meta_http_status(meta)
            if status is not None:
                status_counts[status] = status_counts.get(status, 0) + 1

        if status_counts:
            total_status = sum(status_counts.values())
            print("\nHTTP Status Summary (from metadata):")
            for code, count in sorted(status_counts.items()):
                ratio = (count / total_status) * 100 if total_status else 0
                print(f"  {code}: {count} ({ratio:.1f}%)")

            backend_status: dict[str, dict[int, int]] = {}
            for e in entries:
                meta = e.get("meta", {})
                backend = meta.get("be")
                status = _meta_http_status(meta)
                if not isinstance(backend, str) or not backend:
                    continue
                if status is None:
                    continue
                backend_status.setdefault(backend, {})
                backend_status[backend][status] = (
                    backend_status[backend].get(status, 0) + 1
                )

            if backend_status:
                print("\nHTTP Status by Backend (from metadata):")
                for backend, counts in sorted(backend_status.items()):
                    total_backend = sum(counts.values())
                    rate_limited = counts.get(429, 0)
                    ratio = (rate_limited / total_backend) * 100 if total_backend else 0
                    print(
                        f"  {backend}: 429 {rate_limited}/{total_backend} ({ratio:.1f}%)"
                    )


def format_timestamp(ts: float) -> str:
    """Format a timestamp into a human-readable string."""
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def parse_time_arg(time_str: str, reference_date: datetime.date | None = None) -> float:
    """Parse a time argument into a Unix timestamp.

    Supports:
    - Unix timestamps (integer or float): 1702300000, 1702300000.123
    - ISO datetime: 2024-01-15T10:00:00, 2024-01-15 10:00:00
    - Date only: 2024-01-15
    - Time only: 10:30:00, 10:30 (uses reference_date or today)

    Args:
        time_str: The time string to parse
        reference_date: Reference date for time-only values (defaults to today)

    Returns:
        Unix timestamp as float
    """
    time_str = time_str.strip()

    # Try parsing as Unix timestamp first
    try:
        ts = float(time_str)
        if ts > 0:
            return ts
    except ValueError:
        pass

    # Try ISO datetime formats
    iso_formats = [
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]

    for fmt in iso_formats:
        try:
            dt = datetime.datetime.strptime(time_str, fmt)
            return dt.timestamp()
        except ValueError:
            continue

    # Try time-only formats
    time_formats = [
        "%H:%M:%S.%f",
        "%H:%M:%S",
        "%H:%M",
    ]

    ref_date = reference_date or datetime.date.today()
    for fmt in time_formats:
        try:
            t = datetime.datetime.strptime(time_str, fmt).time()
            dt = datetime.datetime.combine(ref_date, t)
            return dt.timestamp()
        except ValueError:
            continue

    raise ValueError(
        f"Could not parse time: '{time_str}'. "
        "Supported formats: Unix timestamp, ISO datetime (2024-01-15T10:00:00), "
        "date (2024-01-15), or time (10:30:00)"
    )


def filter_entries_by_time(
    entries: list[dict[str, Any]],
    start_time: float | None = None,
    end_time: float | None = None,
) -> list[dict[str, Any]]:
    """Filter entries by time range.

    Args:
        entries: List of capture entry dictionaries
        start_time: Minimum timestamp (inclusive), or None for no lower bound
        end_time: Maximum timestamp (inclusive), or None for no upper bound

    Returns:
        Filtered list of entries
    """
    if start_time is None and end_time is None:
        return entries

    result = []
    for e in entries:
        ts = e.get("ts", 0)
        if start_time is not None and ts < start_time:
            continue
        if end_time is not None and ts > end_time:
            continue
        result.append(e)
    return result


def get_unique_backends(entries: list[dict[str, Any]]) -> dict[str, int]:
    """Extract unique backends from capture entries with their counts.

    Args:
        entries: List of capture entry dictionaries

    Returns:
        Dictionary mapping backend name to count of entries with that backend,
        sorted by count in descending order
    """
    backend_counts: dict[str, int] = {}
    for e in entries:
        meta = e.get("meta", {})
        backend = meta.get("be")
        if backend:
            backend_counts[backend] = backend_counts.get(backend, 0) + 1

    # Sort by count descending
    return dict(sorted(backend_counts.items(), key=lambda x: x[1], reverse=True))


def filter_entries_by_backend(
    entries: list[dict[str, Any]], backend_name: str | None
) -> list[dict[str, Any]]:
    """Filter entries by backend name.

    Args:
        entries: List of capture entry dictionaries
        backend_name: Backend name to filter by, or None for no filtering

    Returns:
        Filtered list of entries
    """
    if backend_name is None:
        return entries

    return [e for e in entries if e.get("meta", {}).get("be") == backend_name]


def hexdump(data: bytes, length: int = 16) -> list[str]:
    """Generate a canonical hex dump of the data."""
    result = []
    for i in range(0, len(data), length):
        chunk = data[i : i + length]
        hex_line = " ".join(f"{b:02x}" for b in chunk)
        ascii_line = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        result.append(f"{i:04x}  {hex_line:<{length*3}}  |{ascii_line}|")
    return result


def get_unique_sessions(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Extract unique session IDs from capture entries with metadata.

    Returns:
        Dictionary mapping session ID to session info (entry count, time range, backend)
    """
    sessions: dict[str, dict[str, Any]] = {}
    for e in entries:
        meta = e.get("meta", {})
        sid = _meta_a_session_id(meta)
        if sid:
            if sid not in sessions:
                sessions[sid] = {
                    "count": 0,
                    "first_ts": e.get("ts", 0),
                    "last_ts": e.get("ts", 0),
                    "backend": meta.get("be", "unknown"),
                }
            sessions[sid]["count"] += 1
            sessions[sid]["last_ts"] = e.get("ts", 0)

    return sessions


def detect_issues(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect issues in capture entries.

    Returns:
        List of issue dictionaries with type, severity, entry, and description
    """
    issues = []

    # Track timing gaps
    for i in range(1, len(entries)):
        prev = entries[i - 1]
        curr = entries[i]
        gap = curr.get("ts", 0) - prev.get("ts", 0)

        # Detect slow responses (>10s gap between consecutive entries in same session)
        if gap > 10:
            prev_meta = prev.get("meta", {})
            curr_meta = curr.get("meta", {})
            if _meta_a_session_id(prev_meta) == _meta_a_session_id(curr_meta):
                issues.append(
                    {
                        "type": "slow_response",
                        "severity": "warning" if gap < 30 else "error",
                        "entry": curr.get("seq"),
                        "description": f"Long gap: {gap:.1f}s between entries [{prev.get('seq')}] and [{curr.get('seq')}]",
                        "gap": gap,
                    }
                )

    # Detect rate limiting and errors
    for e in entries:
        data = e.get("data", b"")
        events = parse_all_sse_events(data)
        for parsed in events:
            error = parsed.get("error")
            if error:
                error_type = error.get("type", "unknown")
                if "rate" in error_type.lower() or "quota" in error_type.lower():
                    issues.append(
                        {
                            "type": "rate_limit",
                            "severity": "warning",
                            "entry": e.get("seq"),
                            "description": f"Rate limiting: {error.get('message', 'Unknown')}",
                        }
                    )
                else:
                    issues.append(
                        {
                            "type": "backend_error",
                            "severity": "error",
                            "entry": e.get("seq"),
                            "description": f"Backend error: {error.get('message', 'Unknown')}",
                        }
                    )

    # Detect stalled requests (client requests that never get a backend response).
    # NOTE: client requests can be interleaved (e.g., chat + title generation), so we
    # must not assume that a C->P request is followed by backend traffic before the
    # next C->P request.
    #
    # Strategy:
    # 1) Correlate C->P to P->B using rid when it matches on the B-leg, else same
    #    A-leg session (asid) within the client request window (B2BUA).
    # 2) For each correlated P->B, verify B->P exists (rid and/or bsid/asid indices).

    # Index proxy->backend requests and backend->proxy responses by rid/session.
    pb_indices_by_rid: dict[str, list[int]] = {}
    bp_indices_by_rid: dict[str, list[int]] = {}
    pb_indices_by_sid: dict[str, list[int]] = {}
    bp_indices_by_sid: dict[str, list[int]] = {}

    for i, e in enumerate(entries):
        meta = e.get("meta", {})
        session_ids: list[str] = []
        a_session_id = _meta_a_session_id(meta)
        b_session_id = _meta_b_session_id(meta)
        if isinstance(a_session_id, str) and a_session_id:
            session_ids.append(a_session_id)
        if (
            isinstance(b_session_id, str)
            and b_session_id
            and b_session_id != a_session_id
        ):
            session_ids.append(b_session_id)
        rid = meta.get("rid")
        if e.get("dir") == 2:
            if isinstance(rid, str) and rid:
                pb_indices_by_rid.setdefault(rid, []).append(i)
            for session_id in session_ids:
                pb_indices_by_sid.setdefault(session_id, []).append(i)
        elif e.get("dir") == 3:
            if isinstance(rid, str) and rid:
                bp_indices_by_rid.setdefault(rid, []).append(i)
            for session_id in session_ids:
                bp_indices_by_sid.setdefault(session_id, []).append(i)

    # Ensure ordering
    for _rid, idxs in pb_indices_by_rid.items():
        idxs.sort()
    for _rid, idxs in bp_indices_by_rid.items():
        idxs.sort()
    for _sid, idxs in pb_indices_by_sid.items():
        idxs.sort()
    for _sid, idxs in bp_indices_by_sid.items():
        idxs.sort()

    for client_idx, e in enumerate(entries):
        if e.get("dir") != 0:
            continue
        meta = e.get("meta", {})
        rid = meta.get("rid")
        if (not isinstance(rid, str) or not rid) and not _meta_a_session_id(meta):
            continue

        pb_candidates = _pb_candidates_after_cp(entries, client_idx, meta)
        if not pb_candidates:
            issues.append(
                {
                    "type": "missing_response",
                    "severity": "warning",
                    "entry": e.get("seq"),
                    "description": (
                        f"Request at [{e.get('seq')}] has no backend request "
                        f"(not forwarded)"
                    ),
                }
            )
            continue

        missing_correlation_meta = True
        all_answered = True
        for pb_idx in pb_candidates:
            pb_meta = entries[pb_idx].get("meta", {})
            if _pb_candidate_session_ids(pb_meta) or _meta_request_id(pb_meta):
                missing_correlation_meta = False
            if not _pb_has_response_for_pb(
                pb_indices_by_sid,
                bp_indices_by_sid,
                pb_indices_by_rid,
                bp_indices_by_rid,
                pb_meta,
                pb_idx,
            ):
                all_answered = False

        if all_answered:
            continue

        if missing_correlation_meta:
            issues.append(
                {
                    "type": "missing_response",
                    "severity": "warning",
                    "entry": e.get("seq"),
                    "description": (
                        f"Request at [{e.get('seq')}] missing backend session/request "
                        f"id for correlation"
                    ),
                }
            )
            continue

        issues.append(
            {
                "type": "missing_response",
                "severity": "error",
                "entry": e.get("seq"),
                "description": (
                    f"Request at [{e.get('seq')}] has incomplete or missing "
                    f"backend response"
                ),
            }
        )

    return issues


def print_timeline(
    entries: list[dict[str, Any]], backend_filter: str | None = None
) -> None:
    """Print a timeline view of entries with timing gaps highlighted."""
    print()
    print("=" * 70)
    print("TIMELINE VIEW")
    print("=" * 70)
    if backend_filter:
        print(f"(Filtered to backend: {backend_filter})")
        print("=" * 70)

    filtered = [
        e
        for e in entries
        if backend_filter is None or e.get("meta", {}).get("be") == backend_filter
    ]

    if not filtered:
        print("No entries to display")
        return

    prev_ts = None
    for e in filtered:
        seq = e.get("seq", "?")
        direction = DIRECTION_SYMBOLS.get(e["dir"], f"?{e['dir']}")
        ts = e.get("ts", 0)
        data_len = len(e.get("data", b""))
        backend = e.get("meta", {}).get("be", "")
        a_session = _meta_a_session_id(e.get("meta", {}))
        b_session = _meta_b_session_id(e.get("meta", {}))

        # Format timestamp
        dt = datetime.datetime.fromtimestamp(ts)
        ts_str = dt.strftime("%H:%M:%S.%f")[:-3]  # Trim to milliseconds

        # Calculate gap from previous entry
        gap_str = ""
        if prev_ts is not None:
            gap = ts - prev_ts
            if gap > 10:
                gap_str = f" !!! +{gap:.1f}s SLOW !!!"
            elif gap > 1:
                gap_str = f" (+{gap:.1f}s)"
            else:
                gap_str = f" (+{gap*1000:.0f}ms)"

        # Format data size
        if data_len > 1024:
            size_str = f"{data_len/1024:.1f}KB"
        else:
            size_str = f"{data_len}B"

        # Build line
        line_parts = [f"[{seq}]", direction, ts_str, gap_str, size_str]
        if backend:
            line_parts.append(f"be={backend}")
        if a_session:
            line_parts.append(f"a={a_session[:8]}")
        if b_session:
            line_parts.append(f"b={b_session[:8]}")

        print("  ".join(part for part in line_parts if part))

        prev_ts = ts


def print_issues_summary(issues: list[dict[str, Any]]) -> None:
    """Print a summary of detected issues."""
    if not issues:
        print("\nNo issues detected!")
        return

    print()
    print("=" * 70)
    print("ISSUES DETECTED")
    print("=" * 70)

    # Group by type
    by_type: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        issue_type = issue["type"]
        if issue_type not in by_type:
            by_type[issue_type] = []
        by_type[issue_type].append(issue)

    for issue_type, type_issues in by_type.items():
        print(
            f"\n{issue_type.upper().replace('_', ' ')} ({len(type_issues)} occurrences):"
        )
        for issue in type_issues:
            severity_symbol = "!!!" if issue["severity"] == "error" else " ! "
            print(
                f"  [{severity_symbol}] Entry [{issue['entry']}]: {issue['description']}"
            )


def print_b2bua_leg_summary(entries: list[dict[str, Any]]) -> None:
    """Summarize A-leg / B-leg pairings seen on PROXY_TO_BACKEND hops."""
    print()
    print("=" * 70)
    print("B2BUA LEG CORRELATION (from P->B metadata)")
    print("=" * 70)

    pair_counts: dict[tuple[str, str], int] = {}
    for e in entries:
        if e.get("dir") != 2:
            continue
        meta = e.get("meta", {})
        a_sid = _meta_a_session_id(meta)
        b_sid = _meta_b_session_id(meta)
        if not a_sid or not b_sid:
            continue
        key = (a_sid, b_sid)
        pair_counts[key] = pair_counts.get(key, 0) + 1

    if not pair_counts:
        print(
            "No A/B session pairs found on P->B entries (non-B2BUA or missing metadata)."
        )
        return

    print(f"\nFound {len(pair_counts)} distinct (a_session, b_session) pair(s):\n")
    for (a_sid, b_sid), count in sorted(
        pair_counts.items(), key=lambda x: (-x[1], x[0][0], x[0][1])
    ):
        print(f"  A-leg: {a_sid}")
        print(f"  B-leg: {b_sid}")
        print(f"  P->B entries: {count}\n")


def group_by_session(entries: list[dict[str, Any]]) -> None:
    """Group and display entries by session ID."""
    print()
    print("=" * 70)
    print("ENTRIES GROUPED BY SESSION")
    print("=" * 70)

    sessions = get_unique_sessions(entries)

    if not sessions:
        print("No session information available")
        return

    print(f"\nFound {len(sessions)} unique session(s):\n")

    for sid, info in sessions.items():
        duration = info["last_ts"] - info["first_ts"]
        print(f"Session: {sid[:16]}... (backend: {info['backend']})")
        print(f"  Entries: {info['count']}, Duration: {duration:.2f}s")

        # Show entries for this session
        session_entries = [
            e for e in entries if _meta_a_session_id(e.get("meta", {})) == sid
        ]
        print(
            f"  Entry range: [{session_entries[0].get('seq')}] to [{session_entries[-1].get('seq')}]"
        )
        print()


def track_request(
    entries: list[dict[str, Any]], request_num: int, backend_filter: str | None = None
) -> None:
    """Track a specific request through the system."""
    print()
    print("=" * 70)
    print(f"REQUEST FLOW TRACKING - Request #{request_num}")
    print("=" * 70)
    if backend_filter:
        print(f"(Filtered to backend: {backend_filter})")
        print("=" * 70)

    bf_norm = backend_filter.strip().lower() if backend_filter else ""
    is_client = bf_norm == "client"

    req_idx: int | None = None
    if is_client:
        req_count = 0
        for i, e in enumerate(entries):
            if e.get("dir") == 0:
                req_count += 1
                if req_count == request_num:
                    req_idx = i
                    break
    else:
        req_count = 0
        for i, e in enumerate(entries):
            if e.get("dir") == 2 and (
                backend_filter is None or e.get("meta", {}).get("be") == backend_filter
            ):
                req_count += 1
                if req_count == request_num:
                    req_idx = i
                    break
        if req_idx is None and backend_filter is None:
            req_count = 0
            for i, e in enumerate(entries):
                if e.get("dir") == 0:
                    req_count += 1
                    if req_count == request_num:
                        req_idx = i
                        break

    if req_idx is None:
        print(f"Request #{request_num} not found")
        return

    req_entry = entries[req_idx]
    anchor_rid = _meta_request_id(req_entry.get("meta", {}))

    def passes_filter(ent: dict[str, Any]) -> bool:
        if backend_filter is None:
            return True
        if is_client:
            return ent.get("dir") in (0, 1)
        direction = ent.get("dir")
        if direction in (0, 1):
            return True
        if anchor_rid:
            ent_rid = _meta_request_id(ent.get("meta", {}))
            if ent_rid and ent_rid != anchor_rid:
                return False
        ent_meta = ent.get("meta", {})
        be = ent_meta.get("be") if isinstance(ent_meta, dict) else None
        return bool(be == backend_filter)

    cp_idx = _find_enclosing_cp_index(entries, req_idx)
    flow_start = cp_idx if cp_idx is not None else req_idx
    anchor_meta = entries[flow_start].get("meta", {})
    flow_end = _cp_window_end_index(entries, flow_start, anchor_meta)

    prefix = [e for e in entries[flow_start:req_idx] if passes_filter(e)]
    suffix = [e for e in entries[req_idx + 1 : flow_end] if passes_filter(e)]
    flow = [*prefix, req_entry, *suffix]

    print(f"\nRequest initiated at entry [{req_entry.get('seq')}]")
    start_ts = req_entry.get("ts", 0)

    try:
        req_data = json.loads(req_entry.get("data", b"").decode("utf-8"))
        print(f"Model: {req_data.get('model', 'N/A')}")
        print(f"Request size: {len(req_entry.get('data', b'')):,} bytes")
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    print("\nFlow timeline:")
    for e in flow:
        seq = e.get("seq", "?")
        direction = DIRECTION_SYMBOLS.get(e["dir"], f"?{e['dir']}")
        ts = e.get("ts", 0)
        delta = ts - start_ts
        data_len = len(e.get("data", b""))

        if e is req_entry:
            start_desc = (
                "Request received" if e.get("dir") == 0 else "Forwarded to backend"
            )
            print(f"  [START] [{seq}] {direction}  {start_desc} (t={delta:.3f}s)")
            continue

        desc = f"{data_len:,} bytes"
        if e["dir"] == 2:
            desc = "Forwarded to backend"
        elif e["dir"] == 3:
            events = parse_all_sse_events(e.get("data", b""))
            if events:
                descriptions = []
                for parsed in events:
                    if parsed.get("error"):
                        descriptions.append(
                            f"ERROR: {parsed['error'].get('message', 'Unknown')[:50]}"
                        )
                    elif any(
                        c.get("delta", {}).get("tool_calls")
                        for c in parsed.get("choices", [])
                    ):
                        descriptions.append("Tool call")
                    elif any(
                        c.get("delta", {}).get("content")
                        for c in parsed.get("choices", [])
                    ):
                        descriptions.append("Content")
                    else:
                        descriptions.append("Meta")

                if any(d.startswith("ERROR") for d in descriptions):
                    desc = next(d for d in descriptions if d.startswith("ERROR"))
                elif "Tool call" in descriptions:
                    desc = (
                        f"Tool call response (+{len(descriptions)-1} other events)"
                        if len(descriptions) > 1
                        else "Tool call response"
                    )
                elif "Content" in descriptions:
                    desc = (
                        f"Content chunk (+{len(descriptions)-1} other events)"
                        if len(descriptions) > 1
                        else "Content chunk"
                    )
                else:
                    desc = "Metadata chunk"
            else:
                desc = f"{len(e.get('data', b''))} bytes (Raw)"
        elif e["dir"] == 1:
            desc = "Forwarded to client"

        if delta > 10:
            desc += " !!! SLOW !!!"

        print(f"  [{direction}] [{seq}] {desc} (t={delta:.3f}s)")


def analyze_streaming(
    entries: list[dict[str, Any]], backend_filter: str | None = None
) -> None:
    """Analyze streaming performance."""
    print()
    print("=" * 70)
    print("STREAMING PERFORMANCE ANALYSIS")
    print("=" * 70)
    if backend_filter:
        print(f"(Filtered to backend: {backend_filter})")
        print("=" * 70)

    seen_backend_request_ids: set[str] = set()
    i = 0
    stream_num = 0
    while i < len(entries):
        e = entries[i]

        if backend_filter is not None and e.get("meta", {}).get("be") != backend_filter:
            i += 1
            continue

        if e["dir"] == 2:
            request_id = _meta_request_id(e.get("meta", {}))
            if request_id:
                if request_id in seen_backend_request_ids:
                    i += 1
                    continue
                seen_backend_request_ids.add(request_id)

            stream_num += 1
            print(f"\n--- Stream #{stream_num} (Entry [{e.get('seq')}]) ---")

            chunks = _collect_backend_response_for_pb(entries, i)
            if not chunks and request_id:
                chunks = _collect_correlated_entries(
                    entries,
                    start_index=i,
                    request_id=request_id,
                    direction=3,
                )

            if not chunks:
                print("  No backend response chunks")
                i += 1
                continue

            # Calculate metrics
            ttft = _compute_backend_ttft(e, chunks)
            duration = _compute_backend_duration(e, chunks)
            payload_chunks = _backend_payload_entries(chunks)
            chunk_count = len(payload_chunks)
            total_bytes = sum(len(c.get("data", b"")) for c in payload_chunks)

            if ttft is not None:
                print(f"  Time to First Token: {ttft:.3f}s")
            if duration is not None:
                print(f"  Total Duration: {duration:.3f}s")
            print(f"  Chunks: {chunk_count}")
            print(f"  Total Data: {total_bytes:,} bytes")

            if chunk_count > 1 and duration is not None:
                avg_chunk_time = duration / (chunk_count - 1)
                print(f"  Avg Time Between Chunks: {avg_chunk_time:.3f}s")

            # Detect slow chunks
            slow_chunks = []
            for k in range(1, len(payload_chunks)):
                gap = payload_chunks[k].get("ts", 0) - payload_chunks[k - 1].get(
                    "ts", 0
                )
                if gap > 5:
                    slow_chunks.append((payload_chunks[k].get("seq"), gap))

            if slow_chunks:
                print("  Slow Chunks Detected:")
                for seq, gap in slow_chunks:
                    print(f"    Entry [{seq}]: {gap:.1f}s gap")

            i += 1
        else:
            i += 1


def parse_entry_range(range_str: str) -> tuple[int, int]:
    """Parse entry range string like '10-20' or '10:20'."""
    separators = ["-", ":", ".."]
    for sep in separators:
        if sep in range_str:
            parts = range_str.split(sep)
            if len(parts) == 2:
                try:
                    start = int(parts[0])
                    end = int(parts[1])
                    return (start, end)
                except ValueError:
                    pass
    raise ValueError(
        f"Invalid range format: {range_str}. Use 'START-END' or 'START:END'"
    )


def print_entries(
    entries: list[dict[str, Any]],
    max_entries: int = 20,
    max_data_length: int = 200,
    direction_filter: int | None = None,
    backend_filter: str | None = None,
    verbose: bool = False,
    search_term: str | None = None,
    session_substring: str | None = None,
    show_hex: bool = False,
    entry_range: tuple[int, int] | None = None,
    show_last: bool = False,
    context_around: int | None = None,
    context_size: int = 5,
    jump_to_entry: int | None = None,
) -> None:
    """Print individual entries with enhanced filtering options."""
    print()
    print("=" * 70)
    print("ENTRIES")
    print("=" * 70)

    # Build filtered list first
    filtered_entries = []
    for e in entries:
        if direction_filter is not None and e["dir"] != direction_filter:
            continue

        if backend_filter is not None and e.get("meta", {}).get("be") != backend_filter:
            continue

        if session_substring:
            ss = session_substring.lower()
            meta = e.get("meta", {})
            if not isinstance(meta, dict):
                meta = {}
            asid = str(meta.get("asid") or meta.get("sid") or "").lower()
            bsid = str(meta.get("bsid") or "").lower()
            if ss not in asid and ss not in bsid:
                continue

        data = e.get("data", b"")

        # Search filter
        if search_term:
            term = search_term.lower()
            data_str = safe_decode(data, len(data)).lower()
            meta_str = str(e.get("meta", {})).lower()

            if term not in data_str and term not in meta_str:
                continue

        filtered_entries.append(e)

    # Apply range/context/last/jump filters
    display_entries = filtered_entries

    if jump_to_entry is not None:
        # Find and show only this entry
        target = [e for e in filtered_entries if e.get("seq") == jump_to_entry]
        if target:
            display_entries = target
            print(f"Showing entry [{jump_to_entry}]")
        else:
            print(f"Warning: Entry [{jump_to_entry}] not found in filtered results")
            display_entries = []

    elif context_around is not None:
        # Find entry with this sequence number
        target_idx = None
        for idx, e in enumerate(filtered_entries):
            if e.get("seq") == context_around:
                target_idx = idx
                break

        if target_idx is not None:
            start_idx = max(0, target_idx - context_size)
            end_idx = min(len(filtered_entries), target_idx + context_size + 1)
            display_entries = filtered_entries[start_idx:end_idx]
            print(
                f"Showing context around entry [{context_around}] ({context_size} before/after)"
            )
        else:
            print(f"Warning: Entry [{context_around}] not found in filtered results")
            display_entries = []

    elif entry_range is not None:
        start_seq, end_seq = entry_range
        display_entries = [
            e for e in filtered_entries if start_seq <= e.get("seq", -1) <= end_seq
        ]
        print(f"Showing entries [{start_seq}] to [{end_seq}]")

    elif show_last:
        display_entries = (
            filtered_entries[-max_entries:] if max_entries > 0 else filtered_entries
        )
        print(f"Showing last {len(display_entries)} entries")

    else:
        # Default: first N entries
        if max_entries > 0 and len(display_entries) > max_entries:
            display_entries = display_entries[:max_entries]

    # Display entries
    for e in display_entries:
        data = e.get("data", b"")
        direction = DIRECTION_SYMBOLS.get(e["dir"], f"?{e['dir']}")
        seq = e.get("seq", "?")
        ts = e.get("ts", 0)
        ts_str = format_timestamp(ts)
        meta = e.get("meta", {})
        backend = meta.get("be", "")
        backend_str = f" | backend={backend}" if backend else ""
        a_session = _meta_a_session_id(meta)
        b_session = _meta_b_session_id(meta)
        session_parts: list[str] = []
        if a_session:
            session_parts.append(f"a={a_session[:8]}")
        if b_session:
            session_parts.append(f"b={b_session[:8]}")
        session_str = " | session=" + ",".join(session_parts) if session_parts else ""
        marker_parts: list[str] = []
        if _meta_is_stream_start(meta):
            marker_parts.append("stream_start")
        if _meta_is_stream_end(meta):
            marker_parts.append("stream_end")
        if meta.get("eos"):
            marker_parts.append("eos")
        marker_str = " | " + ",".join(marker_parts) if marker_parts else ""

        print(
            f"\n[{seq}] {direction} | {len(data):,} bytes | ts={ts_str}{backend_str}{session_str}{marker_str}"
        )

        # Verbose metadata
        if verbose:
            meta = _normalize_metadata(dict(meta))
            # Remove already shown fields
            for key in ["backend", "session_id", "a_session_id", "b_session_id"]:
                meta.pop(key, None)
            if meta:
                print("    Metadata:")
                for k, v in meta.items():
                    if isinstance(v, dict):
                        print(f"      {k}:")
                        for hk, hv in v.items():
                            print(f"        {hk}: {hv}")
                    else:
                        print(f"      {k}: {v}")

        if data:
            if show_hex:
                print("    Hex Dump:")
                for line in hexdump(data[:max_data_length]):
                    print(f"      {line}")
                if len(data) > max_data_length:
                    print(f"      ... ({len(data) - max_data_length} more bytes)")
            else:
                preview = safe_decode(data, max_data_length)
                # Indent the preview
                for line in preview.split("\n")[:5]:
                    print(f"    {line}")
                if len(data) > max_data_length:
                    print(f"    ... ({len(data) - max_data_length} more bytes)")

    # Show summary of what was filtered out
    if (
        not show_last
        and not jump_to_entry
        and not context_around
        and not entry_range
        and max_entries > 0
        and len(filtered_entries) > len(display_entries)
    ):
        remaining = len(filtered_entries) - len(display_entries)
        print(f"\n... and {remaining} more entries (use --last to see final entries)")


def analyze_request_response_pairs(
    entries: list[dict[str, Any]], backend_filter: str | None = None
) -> None:
    """Analyze request/response pairs and detect issues.

    Args:
        entries: List of capture entry dictionaries
        backend_filter: Optional backend name to filter analysis by
    """
    print()
    print("=" * 70)
    print("REQUEST/RESPONSE ANALYSIS")
    print("=" * 70)
    if backend_filter:
        print(f"(Filtered to backend: {backend_filter})")
        print("=" * 70)

    request_num = 0
    i = 0

    while i < len(entries):
        e = entries[i]

        if e["dir"] == 0:  # CLIENT_TO_PROXY (new request)
            backend_entries = _collect_backend_chunks_for_cp(entries, i)
            if backend_filter is not None:
                backend_entries = [
                    entry
                    for entry in backend_entries
                    if entry.get("meta", {}).get("be") == backend_filter
                ]
            if backend_filter is not None and not backend_entries:
                i += 1
                continue

            request_num += 1
            print(f"\n--- REQUEST #{request_num} ---")

            try:
                req = json.loads(e["data"].decode("utf-8"))
                model = req.get("model", "N/A")
                print(f"Model: {model}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                print("Model: (could not parse)")

            client_entries = _collect_client_chunks_for_cp(entries, i)
            client_chunks = [entry.get("data", b"") for entry in client_entries]

            # Analyze backend responses
            backend_content_len = 0
            backend_tool_calls = 0
            backend_tool_names = set()
            backend_models = set()
            issues = []

            # Timing
            if backend_entries:
                ttft = _compute_backend_ttft(e, backend_entries)
                duration = _compute_backend_duration(e, backend_entries)
                timing_parts = []
                if ttft is not None:
                    timing_parts.append(f"TTFT={ttft:.3f}s")
                if duration is not None:
                    timing_parts.append(f"Duration={duration:.3f}s")
                if timing_parts:
                    print(f"Timing: {', '.join(timing_parts)}")

            for entry in backend_entries:
                chunk = entry["data"]
                events = parse_all_sse_events(chunk)

                # Check for non-SSE error if no events found
                if not events and chunk.strip().startswith(b"{"):
                    try:
                        error_json = json.loads(chunk)
                        if "error" in error_json:
                            issues.append(
                                f"Backend Error: {error_json['error'].get('message', 'Unknown error')}"
                            )
                            events.append(error_json)
                    except json.JSONDecodeError:
                        pass

                for parsed in events:
                    model = parsed.get("model", "")
                    if model:
                        backend_models.add(model)

                    # Check for usage-only response
                    usage = parsed.get("usage", {})
                    if usage and usage.get("completion_tokens", 0) == 0:
                        issues.append("Usage-only chunk (completion_tokens=0)")

                    # Check for content
                    choices = parsed.get("choices", [])
                    for choice in choices:
                        delta = choice.get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            backend_content_len += len(content)

                        tool_calls = delta.get("tool_calls")
                        if tool_calls:
                            backend_tool_calls += len(tool_calls)
                            for tc in tool_calls:
                                if "function" in tc and "name" in tc["function"]:
                                    backend_tool_names.add(tc["function"]["name"])

                        if (
                            choice.get("finish_reason") == "stop"
                            and backend_content_len == 0
                            and backend_tool_calls == 0
                        ):
                            issues.append("Immediate stop without content")

                    # Check for fallback
                    msg_id = parsed.get("id", "")
                    if "fallback" in msg_id:
                        issues.append("Fallback mechanism activated")

                    # Note: Internal model names in backend responses are expected
                    # Only flag as leak if they reach the client

            print(f"Backend models: {backend_models or 'N/A'}")
            backend_info = f"{backend_content_len} chars"
            if backend_tool_calls:
                tool_names_str = (
                    f" ({', '.join(sorted(backend_tool_names))})"
                    if backend_tool_names
                    else ""
                )
                backend_info += f", {backend_tool_calls} tool_calls{tool_names_str}"
            print(f"Backend content: {backend_info}")

            # Analyze client responses
            client_content_len = 0
            client_tool_calls = 0
            client_has_finish = False
            client_has_data = False
            client_chunk_sizes = [len(c) for c in client_chunks]
            for chunk in client_chunks:
                if not chunk:
                    continue
                chunk_text = chunk.decode("utf-8", errors="replace").strip()
                if chunk_text and chunk_text != "data: [DONE]":
                    client_has_data = True

                events = parse_all_sse_events(chunk)
                for parsed in events:
                    # Check for internal model names leaking to client
                    client_model = parsed.get("model", "")
                    if client_model and "code-assist" in client_model.lower():
                        issues.append(
                            f"Internal model name leak to client: {client_model}"
                        )

                    choices = parsed.get("choices", [])
                    for choice in choices:
                        delta = choice.get("delta", {})
                        content = delta.get("content", "")
                        client_content_len += len(content)
                        tool_calls = delta.get("tool_calls")
                        if tool_calls:
                            client_tool_calls += len(tool_calls)
                        if choice.get("finish_reason"):
                            client_has_finish = True

            client_info = f"{client_content_len} chars"
            if client_tool_calls:
                client_info += f", {client_tool_calls} tool_calls"
            if client_has_finish:
                client_info += ", finish_reason"
            if not client_has_data and not client_has_finish:
                client_info = "(no data, only [DONE])"
            # Show chunk sizes for debugging
            nonzero_chunks = [s for s in client_chunk_sizes if s > 0]
            if nonzero_chunks:
                client_info += f" [{','.join(str(s) for s in nonzero_chunks)}]"
            print(f"Client received: {client_info}")

            # Report issues
            if issues:
                print("ISSUES:")
                for issue in set(issues):
                    print(f"  [!] {issue}")

            i += 1
        else:
            i += 1


def export_to_json(
    header: dict[str, Any],
    entries: list[dict[str, Any]],
    output_file: str | None,
    backend_filter: str | None = None,
) -> None:
    """Export capture data to JSON format.

    Args:
        header: Capture file header
        entries: List of capture entries
        output_file: Output file path or None for stdout
        backend_filter: Optional backend name to filter by
    """
    entries_list: list[dict[str, Any]] = []
    output: dict[str, Any] = {
        "header": {
            "session_id": header.get("session_id"),
            "created_at": header.get("created_at"),
            "metadata": header.get("metadata", {}),
        },
        "entries": entries_list,
    }

    for e in entries:
        # Apply backend filter
        if backend_filter is not None and e.get("meta", {}).get("be") != backend_filter:
            continue
        meta = e.get("meta", {})
        entry_dict = {
            "seq": e.get("seq"),
            "direction": DIRECTION_NAMES.get(e["dir"], f"Unknown({e['dir']})"),
            "timestamp": e.get("ts"),
            "data_length": len(e.get("data", b"")),
            "metadata": _normalize_metadata(meta),
        }

        # Try to parse as SSE
        parsed = parse_sse_chunk(e.get("data", b""))
        if parsed:
            entry_dict["parsed"] = parsed
        else:
            # Include raw data preview for non-SSE
            data = e.get("data", b"")
            if data:
                entry_dict["data_preview"] = safe_decode(data, 500)

        entries_list.append(entry_dict)

    json_str = json.dumps(output, indent=2, default=str)
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json_str)
        print(f"Exported to {output_file}")
    else:
        print(json_str)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Inspect CBOR wire capture files for debugging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("capture_file", help="Path to the CBOR capture file")
    parser.add_argument(
        "--entries",
        "-e",
        type=int,
        default=0,
        help="Number of entries to display (0 = summary only)",
    )
    parser.add_argument(
        "--analyze",
        "-a",
        action="store_true",
        help="Analyze request/response pairs and detect issues",
    )
    parser.add_argument(
        "--json",
        "-j",
        nargs="?",
        const="-",
        metavar="FILE",
        help="Export to JSON (use - for stdout)",
    )
    parser.add_argument(
        "--direction",
        "-d",
        choices=[
            "client_to_proxy",
            "proxy_to_client",
            "proxy_to_backend",
            "backend_to_proxy",
        ],
        help="Filter entries by direction",
    )
    parser.add_argument(
        "--backend",
        "-b",
        metavar="BACKEND",
        help="Filter entries by backend name (e.g., openai, anthropic, gemini)",
    )
    parser.add_argument(
        "--list-backends",
        "-l",
        action="store_true",
        help="List all unique backends found in the capture file",
    )
    parser.add_argument(
        "--max-data",
        type=int,
        default=200,
        help="Maximum bytes of data to show per entry (default: 200)",
    )
    parser.add_argument(
        "--status-summary",
        action="store_true",
        help="Show HTTP status summary from capture metadata",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed metadata",
    )
    parser.add_argument(
        "--search",
        "-s",
        metavar="TERM",
        help="Filter entries containing the search term (case-insensitive)",
    )
    parser.add_argument(
        "--session-substring",
        metavar="TEXT",
        help=(
            "Only entries whose capture session id (asid/sid or bsid) contains TEXT "
            "(case-insensitive), e.g. OpenCode session suffix"
        ),
    )
    parser.add_argument(
        "--hex",
        action="store_true",
        help="Show hex dump of data instead of text preview",
    )
    parser.add_argument(
        "--last",
        type=int,
        metavar="N",
        help="Show last N entries instead of first N",
    )
    parser.add_argument(
        "--range",
        "-r",
        metavar="START-END",
        help="Show entries in range (e.g., --range 80-98)",
    )
    parser.add_argument(
        "--around",
        type=int,
        metavar="ENTRY",
        help="Show entries around this entry number",
    )
    parser.add_argument(
        "--context",
        "-c",
        type=int,
        default=5,
        metavar="N",
        help="Context size for --around (default: 5)",
    )
    parser.add_argument(
        "--entry",
        type=int,
        metavar="N",
        help="Jump directly to entry N",
    )
    parser.add_argument(
        "--timeline",
        "-t",
        action="store_true",
        help="Show timeline view with timing gaps",
    )
    parser.add_argument(
        "--detect-issues",
        action="store_true",
        help="Automatically detect and report issues",
    )
    parser.add_argument(
        "--group-by-session",
        action="store_true",
        help="Group entries by session ID",
    )
    parser.add_argument(
        "--b2bua",
        action="store_true",
        help="Show A-leg/B-leg session correlation summary (from P->B metadata)",
    )
    parser.add_argument(
        "--track-request",
        type=int,
        metavar="N",
        help="Track request N through the system",
    )
    parser.add_argument(
        "--analyze-streaming",
        action="store_true",
        help="Analyze streaming performance",
    )
    parser.add_argument(
        "--session-id",
        metavar="SID",
        help="Filter by specific session ID",
    )
    parser.add_argument(
        "--start-time",
        metavar="TIME",
        help="Filter entries after this time (Unix timestamp, ISO datetime, or time-only)",
    )
    parser.add_argument(
        "--end-time",
        metavar="TIME",
        help="Filter entries before this time (Unix timestamp, ISO datetime, or time-only)",
    )

    args = parser.parse_args()

    capture_path = Path(args.capture_file)
    if not capture_path.exists():
        print(f"Error: File not found: {capture_path}", file=sys.stderr)
        return 1

    try:
        header, entries = load_capture_file(capture_path)
    except Exception as e:
        print(f"Error loading capture file: {e}", file=sys.stderr)
        return 1

    # Handle --list-backends flag
    if args.list_backends:
        backends = get_unique_backends(entries)
        if not backends:
            print("No backend information available in this capture file")
        else:
            print("=" * 70)
            print("AVAILABLE BACKENDS")
            print("=" * 70)
            for backend, count in backends.items():
                print(f"  {backend}: {count} entries")
        return 0

    # Validate backend filter if specified
    backend_filter = args.backend
    if backend_filter:
        available_backends = get_unique_backends(entries)
        if backend_filter not in available_backends:
            print(
                f"Warning: Backend '{backend_filter}' not found in capture.",
                file=sys.stderr,
            )
            if available_backends:
                backends_str = ", ".join(available_backends.keys())
                print(f"Available backends: {backends_str}", file=sys.stderr)
            else:
                print(
                    "No backend information available in this capture.", file=sys.stderr
                )

    # Handle JSON export
    if args.json:
        output_file = None if args.json == "-" else args.json
        export_to_json(header, entries, output_file, backend_filter=backend_filter)
        return 0

    # Print summary
    print_summary(header, entries, show_status_summary=args.status_summary)

    # Direction filter
    direction_filter = None
    if args.direction:
        direction_map = {
            "client_to_proxy": 0,
            "proxy_to_client": 1,
            "proxy_to_backend": 2,
            "backend_to_proxy": 3,
        }
        direction_filter = direction_map[args.direction]

    # Apply session filter if specified
    if args.session_id:
        entries = [
            e
            for e in entries
            if _meta_a_session_id(e.get("meta", {})) == args.session_id
        ]
        if not entries:
            print(
                f"No entries found for session ID: {args.session_id}", file=sys.stderr
            )
            return 1
        print(f"Filtered to session: {args.session_id}")
        print()

    # Apply time filters if specified
    start_time = None
    end_time = None
    if args.start_time:
        try:
            start_time = parse_time_arg(args.start_time)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    if args.end_time:
        try:
            end_time = parse_time_arg(args.end_time)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    if start_time is not None or end_time is not None:
        original_count = len(entries)
        entries = filter_entries_by_time(entries, start_time, end_time)
        if not entries:
            print("No entries found in specified time range", file=sys.stderr)
            return 1
        time_info = []
        if start_time:
            time_info.append(f"after {format_timestamp(start_time)}")
        if end_time:
            time_info.append(f"before {format_timestamp(end_time)}")
        print(f"Filtered to entries {' and '.join(time_info)}")
        print(f"Matched {len(entries)} of {original_count} entries")
        print()

    # Parse range if specified
    entry_range = None
    if args.range:
        try:
            entry_range = parse_entry_range(args.range)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # Handle timeline view
    if args.timeline:
        print_timeline(entries, backend_filter=backend_filter)

    # Handle issue detection
    if args.detect_issues:
        issues = detect_issues(entries)
        print_issues_summary(issues)

    # Handle session grouping
    if args.group_by_session:
        group_by_session(entries)

    if args.b2bua:
        print_b2bua_leg_summary(entries)

    # Handle request tracking
    if args.track_request:
        track_request(entries, args.track_request, backend_filter=backend_filter)

    # Handle streaming analysis
    if args.analyze_streaming:
        analyze_streaming(entries, backend_filter=backend_filter)

    # Print entries if requested or if search is active
    show_entries = (
        args.entries > 0
        or args.search
        or args.session_substring
        or args.last
        or args.range
        or args.around is not None
        or args.entry is not None
    )

    if show_entries:
        # Determine max_entries
        if args.last:
            max_entries = args.last
        elif args.entries > 0:
            max_entries = args.entries
        elif args.search or args.session_substring:
            max_entries = len(entries)  # Show all matches
        else:
            max_entries = 20  # Default

        print_entries(
            entries,
            max_entries=max_entries,
            max_data_length=args.max_data,
            direction_filter=direction_filter,
            backend_filter=backend_filter,
            verbose=args.verbose,
            search_term=args.search,
            session_substring=args.session_substring,
            show_hex=args.hex,
            entry_range=entry_range,
            show_last=args.last is not None,
            context_around=args.around,
            context_size=args.context,
            jump_to_entry=args.entry,
        )

    # Analyze if requested
    if args.analyze:
        analyze_request_response_pairs(entries, backend_filter=backend_filter)

    return 0


if __name__ == "__main__":
    sys.exit(main())
