"""Human-readable console output for capture inspection."""

from __future__ import annotations

import datetime
import sys
from typing import Any, TextIO

from src.core.wire_capture.inspection.constants import (
    DIRECTION_NAMES,
    DIRECTION_SYMBOLS,
)
from src.core.wire_capture.inspection.filters import (
    format_timestamp,
    get_unique_sessions,
)
from src.core.wire_capture.inspection.metadata import (
    meta_a_session_id,
    meta_b_session_id,
    meta_http_status,
    meta_is_stream_end,
    meta_is_stream_start,
    normalize_metadata,
)
from src.core.wire_capture.inspection.payload import hexdump, safe_decode
from src.core.wire_capture.inspection.text_output import writeln


def print_summary(
    header: dict[str, Any],
    entries: list[dict[str, Any]],
    *,
    out: TextIO | None = None,
    show_status_summary: bool = False,
) -> None:
    """Print a summary of the capture file."""
    out = out or sys.stdout
    writeln(out, "=" * 70)
    writeln(out, "CAPTURE FILE SUMMARY")
    writeln(out, "=" * 70)
    writeln(out, f"Session ID: {header.get('session_id', 'N/A')}")
    writeln(out, f"Created At: {header.get('created_at', 'N/A')}")
    writeln(out, f"Total Entries: {len(entries)}")
    writeln(out)

    direction_counts: dict[int, int] = {}
    total_bytes = 0
    for e in entries:
        d = e["dir"]
        direction_counts[d] = direction_counts.get(d, 0) + 1
        total_bytes += len(e.get("data", b""))

    writeln(out, "Direction Counts:")
    for d, count in sorted(direction_counts.items()):
        writeln(out, f"  {DIRECTION_NAMES.get(d, f'Unknown({d})')}: {count}")
    writeln(out, f"\nTotal Bytes: {total_bytes:,}")

    if len(entries) >= 2:
        first_ts = entries[0].get("ts", 0)
        last_ts = entries[-1].get("ts", 0)
        duration = last_ts - first_ts
        writeln(out, f"Duration: {duration:.2f}s")

    if show_status_summary:
        status_counts: dict[int, int] = {}
        for e in entries:
            meta = e.get("meta", {})
            status = meta_http_status(meta)
            if status is not None:
                status_counts[status] = status_counts.get(status, 0) + 1

        if status_counts:
            total_status = sum(status_counts.values())
            writeln(out, "\nHTTP Status Summary (from metadata):")
            for code, count in sorted(status_counts.items()):
                ratio = (count / total_status) * 100 if total_status else 0
                writeln(out, f"  {code}: {count} ({ratio:.1f}%)")

            backend_status: dict[str, dict[int, int]] = {}
            for e in entries:
                meta = e.get("meta", {})
                backend = meta.get("be")
                status = meta_http_status(meta)
                if not isinstance(backend, str) or not backend:
                    continue
                if status is None:
                    continue
                backend_status.setdefault(backend, {})
                backend_status[backend][status] = (
                    backend_status[backend].get(status, 0) + 1
                )

            if backend_status:
                writeln(out, "\nHTTP Status by Backend (from metadata):")
                for backend, counts in sorted(backend_status.items()):
                    total_backend = sum(counts.values())
                    rate_limited = counts.get(429, 0)
                    ratio = (rate_limited / total_backend) * 100 if total_backend else 0
                    writeln(
                        out,
                        f"  {backend}: 429 {rate_limited}/{total_backend} ({ratio:.1f}%)",
                    )


def print_timeline(
    entries: list[dict[str, Any]],
    *,
    out: TextIO | None = None,
    backend_filter: str | None = None,
) -> None:
    """Print a timeline view of entries with timing gaps highlighted."""
    out = out or sys.stdout
    writeln(out)
    writeln(out, "=" * 70)
    writeln(out, "TIMELINE VIEW")
    writeln(out, "=" * 70)
    if backend_filter:
        writeln(out, f"(Filtered to backend: {backend_filter})")
        writeln(out, "=" * 70)

    filtered = [
        e
        for e in entries
        if backend_filter is None or e.get("meta", {}).get("be") == backend_filter
    ]

    if not filtered:
        writeln(out, "No entries to display")
        return

    prev_ts = None
    for e in filtered:
        seq = e.get("seq", "?")
        direction = DIRECTION_SYMBOLS.get(e["dir"], f"?{e['dir']}")
        ts = e.get("ts", 0)
        data_len = len(e.get("data", b""))
        backend = e.get("meta", {}).get("be", "")
        a_session = meta_a_session_id(e.get("meta", {}))
        b_session = meta_b_session_id(e.get("meta", {}))

        dt = datetime.datetime.fromtimestamp(ts)
        ts_str = dt.strftime("%H:%M:%S.%f")[:-3]

        gap_str = ""
        if prev_ts is not None:
            gap = ts - prev_ts
            if gap > 10:
                gap_str = f" !!! +{gap:.1f}s SLOW !!!"
            elif gap > 1:
                gap_str = f" (+{gap:.1f}s)"
            else:
                gap_str = f" (+{gap*1000:.0f}ms)"

        if data_len > 1024:
            size_str = f"{data_len/1024:.1f}KB"
        else:
            size_str = f"{data_len}B"

        line_parts = [f"[{seq}]", direction, ts_str, gap_str, size_str]
        if backend:
            line_parts.append(f"be={backend}")
        if a_session:
            line_parts.append(f"a={a_session[:8]}")
        if b_session:
            line_parts.append(f"b={b_session[:8]}")

        writeln(out, "  ".join(part for part in line_parts if part))

        prev_ts = ts


def print_issues_summary(
    issues: list[dict[str, Any]], *, out: TextIO | None = None
) -> None:
    """Print a summary of detected issues."""
    out = out or sys.stdout
    if not issues:
        writeln(out, "\nNo issues detected!")
        return

    writeln(out)
    writeln(out, "=" * 70)
    writeln(out, "ISSUES DETECTED")
    writeln(out, "=" * 70)

    by_type: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        issue_type = issue["type"]
        if issue_type not in by_type:
            by_type[issue_type] = []
        by_type[issue_type].append(issue)

    for issue_type, type_issues in by_type.items():
        writeln(
            out,
            f"\n{issue_type.upper().replace('_', ' ')} ({len(type_issues)} occurrences):",
        )
        for issue in type_issues:
            severity_symbol = "!!!" if issue["severity"] == "error" else " ! "
            writeln(
                out,
                f"  [{severity_symbol}] Entry [{issue['entry']}]: {issue['description']}",
            )


def print_b2bua_leg_summary(
    entries: list[dict[str, Any]], *, out: TextIO | None = None
) -> None:
    """Summarize A-leg / B-leg pairings seen on PROXY_TO_BACKEND hops."""
    out = out or sys.stdout
    writeln(out)
    writeln(out, "=" * 70)
    writeln(out, "B2BUA LEG CORRELATION (from P->B metadata)")
    writeln(out, "=" * 70)

    pair_counts: dict[tuple[str, str], int] = {}
    for e in entries:
        if e.get("dir") != 2:
            continue
        meta = e.get("meta", {})
        a_sid = meta_a_session_id(meta)
        b_sid = meta_b_session_id(meta)
        if not a_sid or not b_sid:
            continue
        key = (a_sid, b_sid)
        pair_counts[key] = pair_counts.get(key, 0) + 1

    if not pair_counts:
        writeln(
            out,
            "No A/B session pairs found on P->B entries (non-B2BUA or missing metadata).",
        )
        return

    writeln(
        out,
        f"\nFound {len(pair_counts)} distinct (a_session, b_session) pair(s):\n",
    )
    for (a_sid, b_sid), count in sorted(
        pair_counts.items(), key=lambda x: (-x[1], x[0][0], x[0][1])
    ):
        writeln(out, f"  A-leg: {a_sid}")
        writeln(out, f"  B-leg: {b_sid}")
        writeln(out, f"  P->B entries: {count}\n")


def group_by_session(
    entries: list[dict[str, Any]], *, out: TextIO | None = None
) -> None:
    """Group and display entries by session ID."""
    out = out or sys.stdout
    writeln(out)
    writeln(out, "=" * 70)
    writeln(out, "ENTRIES GROUPED BY SESSION")
    writeln(out, "=" * 70)

    sessions = get_unique_sessions(entries)

    if not sessions:
        writeln(out, "No session information available")
        return

    writeln(out, f"\nFound {len(sessions)} unique session(s):\n")

    for sid, info in sessions.items():
        duration = info["last_ts"] - info["first_ts"]
        writeln(out, f"Session: {sid[:16]}... (backend: {info['backend']})")
        writeln(out, f"  Entries: {info['count']}, Duration: {duration:.2f}s")

        session_entries = [
            e for e in entries if meta_a_session_id(e.get("meta", {})) == sid
        ]
        writeln(
            out,
            f"  Entry range: [{session_entries[0].get('seq')}] to "
            f"[{session_entries[-1].get('seq')}]",
        )
        writeln(out)


def print_entries(
    entries: list[dict[str, Any]],
    *,
    out: TextIO | None = None,
    max_entries: int = 20,
    max_data_length: int = 4096,
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
    out = out or sys.stdout
    writeln(out)
    writeln(out, "=" * 70)
    writeln(out, "ENTRIES")
    writeln(out, "=" * 70)

    filtered_entries: list[dict[str, Any]] = []
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

        if search_term:
            term = search_term.lower()
            data_str = safe_decode(data, len(data)).lower()
            meta_str = str(e.get("meta", {})).lower()

            if term not in data_str and term not in meta_str:
                continue

        filtered_entries.append(e)

    display_entries = filtered_entries

    if jump_to_entry is not None:
        target = [e for e in filtered_entries if e.get("seq") == jump_to_entry]
        if target:
            display_entries = target
            writeln(out, f"Showing entry [{jump_to_entry}]")
        else:
            writeln(
                out,
                f"Warning: Entry [{jump_to_entry}] not found in filtered results",
            )
            display_entries = []

    elif context_around is not None:
        target_idx = None
        for idx, e in enumerate(filtered_entries):
            if e.get("seq") == context_around:
                target_idx = idx
                break

        if target_idx is not None:
            start_idx = max(0, target_idx - context_size)
            end_idx = min(len(filtered_entries), target_idx + context_size + 1)
            display_entries = filtered_entries[start_idx:end_idx]
            writeln(
                out,
                f"Showing context around entry [{context_around}] "
                f"({context_size} before/after)",
            )
        else:
            writeln(
                out,
                f"Warning: Entry [{context_around}] not found in filtered results",
            )
            display_entries = []

    elif entry_range is not None:
        start_seq, end_seq = entry_range
        display_entries = [
            e for e in filtered_entries if start_seq <= e.get("seq", -1) <= end_seq
        ]
        writeln(out, f"Showing entries [{start_seq}] to [{end_seq}]")

    elif show_last:
        display_entries = (
            filtered_entries[-max_entries:] if max_entries > 0 else filtered_entries
        )
        writeln(out, f"Showing last {len(display_entries)} entries")

    else:
        if max_entries > 0 and len(display_entries) > max_entries:
            display_entries = display_entries[:max_entries]

    for e in display_entries:
        data = e.get("data", b"")
        direction = DIRECTION_SYMBOLS.get(e["dir"], f"?{e['dir']}")
        seq = e.get("seq", "?")
        ts = e.get("ts", 0)
        ts_str = format_timestamp(ts)
        meta = e.get("meta", {})
        backend = meta.get("be", "")
        backend_str = f" | backend={backend}" if backend else ""
        a_session = meta_a_session_id(meta)
        b_session = meta_b_session_id(meta)
        session_parts: list[str] = []
        if a_session:
            session_parts.append(f"a={a_session[:8]}")
        if b_session:
            session_parts.append(f"b={b_session[:8]}")
        session_str = " | session=" + ",".join(session_parts) if session_parts else ""
        marker_parts: list[str] = []
        if meta_is_stream_start(meta):
            marker_parts.append("stream_start")
        if meta_is_stream_end(meta):
            marker_parts.append("stream_end")
        if meta.get("eos"):
            marker_parts.append("eos")
        marker_str = " | " + ",".join(marker_parts) if marker_parts else ""

        writeln(
            out,
            f"\n[{seq}] {direction} | {len(data):,} bytes | ts={ts_str}"
            f"{backend_str}{session_str}{marker_str}",
        )

        if verbose:
            meta = normalize_metadata(dict(meta))
            for key in ["backend", "session_id", "a_session_id", "b_session_id"]:
                meta.pop(key, None)
            if meta:
                writeln(out, "    Metadata:")
                for k, v in meta.items():
                    if isinstance(v, dict):
                        writeln(out, f"      {k}:")
                        for hk, hv in v.items():
                            writeln(out, f"        {hk}: {hv}")
                    else:
                        writeln(out, f"      {k}: {v}")

        if data:
            if show_hex:
                writeln(out, "    Hex Dump:")
                for line in hexdump(data[:max_data_length]):
                    writeln(out, f"      {line}")
                if len(data) > max_data_length:
                    writeln(
                        out,
                        f"      ... ({len(data) - max_data_length} more bytes)",
                    )
            else:
                preview = safe_decode(data, max_data_length)
                for line in preview.split("\n")[:5]:
                    writeln(out, f"    {line}")
                if len(data) > max_data_length:
                    writeln(out, f"    ... ({len(data) - max_data_length} more bytes)")

    if (
        not show_last
        and not jump_to_entry
        and not context_around
        and not entry_range
        and max_entries > 0
        and len(filtered_entries) > len(display_entries)
    ):
        remaining = len(filtered_entries) - len(display_entries)
        writeln(
            out,
            f"\n... and {remaining} more entries (use --last to see final entries)",
        )
