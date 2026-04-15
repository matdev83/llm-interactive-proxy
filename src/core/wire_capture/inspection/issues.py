"""Heuristic issue detection for capture entries."""

from __future__ import annotations

from typing import Any

from src.core.wire_capture.inspection.correlation import (
    pb_candidate_session_ids,
    pb_candidates_after_cp,
    pb_has_response_for_pb,
)
from src.core.wire_capture.inspection.metadata import meta_a_session_id, meta_request_id
from src.core.wire_capture.inspection.payload import parse_all_sse_events


def detect_issues(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect issues in capture entries."""
    issues: list[dict[str, Any]] = []

    for i in range(1, len(entries)):
        prev = entries[i - 1]
        curr = entries[i]
        gap = curr.get("ts", 0) - prev.get("ts", 0)

        if gap > 10:
            prev_meta = prev.get("meta", {})
            curr_meta = curr.get("meta", {})
            if meta_a_session_id(prev_meta) == meta_a_session_id(curr_meta):
                issues.append(
                    {
                        "type": "slow_response",
                        "severity": "warning" if gap < 30 else "error",
                        "entry": curr.get("seq"),
                        "description": (
                            f"Long gap: {gap:.1f}s between entries [{prev.get('seq')}] "
                            f"and [{curr.get('seq')}]"
                        ),
                        "gap": gap,
                    }
                )

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
                            "description": (
                                f"Rate limiting: {error.get('message', 'Unknown')}"
                            ),
                        }
                    )
                else:
                    issues.append(
                        {
                            "type": "backend_error",
                            "severity": "error",
                            "entry": e.get("seq"),
                            "description": (
                                f"Backend error: {error.get('message', 'Unknown')}"
                            ),
                        }
                    )

    pb_indices_by_rid: dict[str, list[int]] = {}
    bp_indices_by_rid: dict[str, list[int]] = {}
    pb_indices_by_sid: dict[str, list[int]] = {}
    bp_indices_by_sid: dict[str, list[int]] = {}

    for i, e in enumerate(entries):
        meta = e.get("meta", {})
        session_ids: list[str] = []
        a_session_id = meta_a_session_id(meta)
        b_session_id = meta.get("bsid")
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
        if (not isinstance(rid, str) or not rid) and not meta_a_session_id(meta):
            continue

        pb_candidates = pb_candidates_after_cp(entries, client_idx, meta)
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
            if pb_candidate_session_ids(pb_meta) or meta_request_id(pb_meta):
                missing_correlation_meta = False
            if not pb_has_response_for_pb(
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
