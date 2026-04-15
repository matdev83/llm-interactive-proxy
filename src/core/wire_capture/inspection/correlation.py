"""B2BUA-aware request/response correlation for capture entries."""

from __future__ import annotations

import bisect
from typing import Any

from src.core.wire_capture.inspection.metadata import (
    meta_a_session_id,
    meta_b_session_id,
    meta_is_stream_end,
    meta_request_id,
)


def backend_payload_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return backend entries that carry actual bytes, not stream markers."""
    result: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("dir") != 3:
            continue
        if entry.get("data"):
            result.append(entry)
    return result


def entry_timestamp(entry: dict[str, Any]) -> float:
    """Return an entry timestamp as float with a safe fallback."""
    ts = entry.get("ts", 0)
    return float(ts) if isinstance(ts, int | float) else 0.0


def compute_backend_ttft(
    request_entry: dict[str, Any], backend_entries: list[dict[str, Any]]
) -> float | None:
    """Compute TTFT using explicit V2 metadata when available."""
    for entry in backend_entries:
        meta = entry.get("meta", {})
        ttfb_ms = meta.get("ttfb")
        if isinstance(ttfb_ms, int | float):
            return float(ttfb_ms) / 1000.0

    payload_entries = backend_payload_entries(backend_entries)
    if payload_entries:
        return entry_timestamp(payload_entries[0]) - entry_timestamp(request_entry)

    if backend_entries:
        return entry_timestamp(backend_entries[0]) - entry_timestamp(request_entry)

    return None


def compute_backend_duration(
    request_entry: dict[str, Any], backend_entries: list[dict[str, Any]]
) -> float | None:
    """Compute request duration using stream-end metadata when available."""
    for entry in reversed(backend_entries):
        meta = entry.get("meta", {})
        if meta_is_stream_end(meta):
            sdur = meta.get("sdur")
            if isinstance(sdur, int | float):
                return float(sdur) / 1000.0
            lat = meta.get("lat")
            if isinstance(lat, int | float):
                return float(lat) / 1000.0
            return entry_timestamp(entry) - entry_timestamp(request_entry)

    payload_entries = backend_payload_entries(backend_entries)
    if payload_entries:
        return entry_timestamp(payload_entries[-1]) - entry_timestamp(request_entry)

    if backend_entries:
        return entry_timestamp(backend_entries[-1]) - entry_timestamp(request_entry)

    return None


def cp_window_end_index(
    entries: list[dict[str, Any]], client_idx: int, client_meta: dict[str, Any]
) -> int:
    """Exclusive end index for the client request at client_idx."""
    a_sid = meta_a_session_id(client_meta)
    if not a_sid:
        return len(entries)
    for k in range(client_idx + 1, len(entries)):
        if entries[k].get("dir") != 0:
            continue
        next_meta = entries[k].get("meta", {})
        if meta_a_session_id(next_meta) == a_sid:
            return k
    return len(entries)


def pb_candidates_after_cp(
    entries: list[dict[str, Any]],
    client_idx: int,
    client_meta: dict[str, Any],
) -> list[int]:
    """Indices of P->B entries that forward this client request (B2BUA-aware)."""
    client_rid = meta_request_id(client_meta)
    end = cp_window_end_index(entries, client_idx, client_meta)
    by_rid: list[int] = []
    for i in range(client_idx + 1, end):
        if entries[i].get("dir") != 2:
            continue
        if client_rid and meta_request_id(entries[i].get("meta", {})) == client_rid:
            by_rid.append(i)
    if by_rid:
        return by_rid

    a_sid = meta_a_session_id(client_meta)
    if not a_sid:
        return []

    result: list[int] = []
    for i in range(client_idx + 1, end):
        if entries[i].get("dir") != 2:
            continue
        if meta_a_session_id(entries[i].get("meta", {})) == a_sid:
            result.append(i)
    return result


def pb_has_response_by_rid(
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


def pb_candidate_session_ids(pb_meta: dict[str, Any]) -> list[str]:
    """Session ids carried on a P->B entry for B->P correlation (A-leg and B-leg)."""
    candidate_ids: list[str] = []
    a_session_id = meta_a_session_id(pb_meta)
    b_session_id = meta_b_session_id(pb_meta)
    if isinstance(a_session_id, str) and a_session_id:
        candidate_ids.append(a_session_id)
    if isinstance(b_session_id, str) and b_session_id and b_session_id != a_session_id:
        candidate_ids.append(b_session_id)
    return candidate_ids


def pb_has_response_by_session(
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


def pb_has_response_for_pb(
    pb_indices_by_sid: dict[str, list[int]],
    bp_indices_by_sid: dict[str, list[int]],
    pb_indices_by_rid: dict[str, list[int]],
    bp_indices_by_rid: dict[str, list[int]],
    pb_meta: dict[str, Any],
    pb_idx: int,
) -> bool:
    """Whether this P->B sees a correlated B->P (rid first, then B-leg / A-leg sid)."""
    rid = meta_request_id(pb_meta)
    if rid and pb_has_response_by_rid(
        pb_indices_by_rid, bp_indices_by_rid, rid, pb_idx
    ):
        return True

    b_session_id = meta_b_session_id(pb_meta)
    if (
        isinstance(b_session_id, str)
        and b_session_id
        and pb_has_response_by_session(
            pb_indices_by_sid, bp_indices_by_sid, pb_idx, b_session_id
        )
    ):
        return True

    for session_id in pb_candidate_session_ids(pb_meta):
        if session_id == b_session_id:
            continue
        if pb_has_response_by_session(
            pb_indices_by_sid, bp_indices_by_sid, pb_idx, session_id
        ):
            return True
    return False


def collect_backend_response_for_pb(
    entries: list[dict[str, Any]], pb_idx: int
) -> list[dict[str, Any]]:
    """B->P chunks for one P->B hop."""
    pb_meta = entries[pb_idx].get("meta", {})
    b_rid = meta_request_id(pb_meta)
    b_sid = meta_b_session_id(pb_meta)
    chunks: list[dict[str, Any]] = []

    for j in range(pb_idx + 1, len(entries)):
        e = entries[j]
        if e.get("dir") == 0:
            break
        if e.get("dir") == 2:
            next_meta = e.get("meta", {})
            if b_sid and meta_b_session_id(next_meta) == b_sid:
                break
            continue
        if e.get("dir") == 3:
            m = e.get("meta", {})
            if (
                b_rid
                and meta_request_id(m) == b_rid
                or b_sid
                and meta_b_session_id(m) == b_sid
                or not b_rid
                and not b_sid
            ):
                chunks.append(e)

    return chunks


def collect_correlated_entries(
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
            and meta_request_id(entry.get("meta", {})) == request_id
        ]

    result: list[dict[str, Any]] = []
    for entry in entries[start_index + 1 :]:
        if entry.get("dir") == 0:
            break
        if entry.get("dir") == direction:
            result.append(entry)
    return result


def collect_backend_chunks_for_cp(
    entries: list[dict[str, Any]], cp_idx: int
) -> list[dict[str, Any]]:
    """All B->P payload flow for the client request at cp_idx (rid or B2BUA window)."""
    cp_meta = entries[cp_idx].get("meta", {})
    rid = meta_request_id(cp_meta)
    if rid:
        correlated = collect_correlated_entries(
            entries, start_index=cp_idx, request_id=rid, direction=3
        )
        if correlated:
            return correlated

    seen_seq: set[Any] = set()
    ordered: list[dict[str, Any]] = []
    for pb_idx in pb_candidates_after_cp(entries, cp_idx, cp_meta):
        for chunk in collect_backend_response_for_pb(entries, pb_idx):
            seq = chunk.get("seq")
            if seq in seen_seq:
                continue
            seen_seq.add(seq)
            ordered.append(chunk)

    ordered.sort(key=lambda e: (e.get("seq", 0), entry_timestamp(e)))
    if ordered:
        return ordered

    return collect_correlated_entries(
        entries, start_index=cp_idx, request_id=None, direction=3
    )


def collect_proxy_to_client_after_cp(
    entries: list[dict[str, Any]], cp_idx: int
) -> list[dict[str, Any]]:
    """P->C entries for this client request when rid correlation fails (B2BUA)."""
    cp_meta = entries[cp_idx].get("meta", {})
    a_sid = meta_a_session_id(cp_meta)
    cp_rid = meta_request_id(cp_meta)
    out: list[dict[str, Any]] = []

    if a_sid:
        end = cp_window_end_index(entries, cp_idx, cp_meta)
        for j in range(cp_idx + 1, end):
            e = entries[j]
            if e.get("dir") != 1:
                continue
            em = e.get("meta", {})
            if meta_a_session_id(em) == a_sid:
                out.append(e)
        return out

    for j in range(cp_idx + 1, len(entries)):
        e = entries[j]
        if e.get("dir") == 0:
            break
        if e.get("dir") != 1:
            continue
        if cp_rid and meta_request_id(e.get("meta", {})) != cp_rid:
            continue
        out.append(e)
    return out


def collect_client_chunks_for_cp(
    entries: list[dict[str, Any]], cp_idx: int
) -> list[dict[str, Any]]:
    rid = meta_request_id(entries[cp_idx].get("meta", {}))
    correlated = collect_correlated_entries(
        entries, start_index=cp_idx, request_id=rid, direction=1
    )
    if correlated:
        return correlated
    return collect_proxy_to_client_after_cp(entries, cp_idx)


def find_enclosing_cp_index(entries: list[dict[str, Any]], from_idx: int) -> int | None:
    """Nearest CLIENT_TO_PROXY at or before from_idx on the same A-leg, if any."""
    meta = entries[from_idx].get("meta", {})
    a_sid = meta_a_session_id(meta)
    for k in range(from_idx, -1, -1):
        if entries[k].get("dir") != 0:
            continue
        if not a_sid:
            return k
        if meta_a_session_id(entries[k].get("meta", {})) == a_sid:
            return k
    return None


def collect_request_flow_entries(
    entries: list[dict[str, Any]],
    *,
    start_index: int,
    backend_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Collect all later entries that belong to the same request flow."""
    start_entry = entries[start_index]
    request_id = meta_request_id(start_entry.get("meta", {}))
    if request_id:
        return [
            entry
            for entry in entries[start_index + 1 :]
            if meta_request_id(entry.get("meta", {})) == request_id
        ]

    def passes_backend_filter(entry: dict[str, Any], bf: str | None) -> bool:
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
        if not passes_backend_filter(entry, backend_filter):
            continue
        related.append(entry)
    return related
