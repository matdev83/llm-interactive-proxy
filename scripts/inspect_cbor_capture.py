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
    return header, entries


def print_summary(header: dict[str, Any], entries: list[dict[str, Any]]) -> None:
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
        sid = meta.get("sid")
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
            if prev_meta.get("sid") == curr_meta.get("sid"):
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

    # Detect stalled sessions (requests with no backend response)
    request_indices = [i for i, e in enumerate(entries) if e["dir"] == 0]
    for req_idx in request_indices:
        # Look for backend response after this request
        has_response = False
        for i in range(req_idx + 1, len(entries)):
            if entries[i]["dir"] == 0:  # Next request
                break
            if entries[i]["dir"] == 3:  # Backend to proxy
                has_response = True
                break

        if not has_response:
            issues.append(
                {
                    "type": "missing_response",
                    "severity": "error",
                    "entry": entries[req_idx].get("seq"),
                    "description": f"Request at [{entries[req_idx].get('seq')}] has no backend response",
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
        session = e.get("meta", {}).get("sid", "")[:8]

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
        if session:
            line_parts.append(f"sid={session}")

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
        session_entries = [e for e in entries if e.get("meta", {}).get("sid") == sid]
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

    # Find the Nth request (looking at PROXY_TO_BACKEND with backend filter)
    req_count = 0
    req_idx = None
    for i, e in enumerate(entries):
        # For backend filtering, look at proxy-to-backend entries
        if e["dir"] == 2:  # PROXY_TO_BACKEND
            if backend_filter is None or e.get("meta", {}).get("be") == backend_filter:
                req_count += 1
                if req_count == request_num:
                    req_idx = i
                    break

    # If no backend filter, also accept CLIENT_TO_PROXY
    if req_idx is None and backend_filter is None:
        req_count = 0
        for i, e in enumerate(entries):
            if e["dir"] == 0:  # CLIENT_TO_PROXY
                req_count += 1
                if req_count == request_num:
                    req_idx = i
                    break

    if req_idx is None:
        print(f"Request #{request_num} not found")
        return

    # Collect all related entries
    req_entry = entries[req_idx]
    related = [req_entry]
    req_backend = req_entry.get("meta", {}).get("be")

    # Find all entries until next request (to same backend or any new client request)
    for i in range(req_idx + 1, len(entries)):
        next_entry = entries[i]
        # Stop at next request to same backend, or any CLIENT_TO_PROXY
        if (
            next_entry["dir"] == 2
            and next_entry.get("meta", {}).get("be") == req_backend
        ):
            break
        if next_entry["dir"] == 0:  # CLIENT_TO_PROXY
            break
        related.append(next_entry)

    # Display flow
    print(f"\nRequest initiated at entry [{req_entry.get('seq')}]")
    start_ts = req_entry.get("ts", 0)

    # Try to parse request details
    try:
        req_data = json.loads(req_entry.get("data", b"").decode("utf-8"))
        print(f"Model: {req_data.get('model', 'N/A')}")
        print(f"Request size: {len(req_entry.get('data', b'')):,} bytes")
    except:
        pass

    print("\nFlow timeline:")
    print(f"  [START] [{req_entry.get('seq')}] C->P  Request received (t=0.000s)")

    for e in related[1:]:
        seq = e.get("seq", "?")
        direction = DIRECTION_SYMBOLS.get(e["dir"], f"?{e['dir']}")
        ts = e.get("ts", 0)
        delta = ts - start_ts
        data_len = len(e.get("data", b""))

        # Try to describe the entry
        desc = f"{data_len:,} bytes"
        if e["dir"] == 2:  # PROXY_TO_BACKEND
            desc = "Forwarded to backend"
        elif e["dir"] == 3:  # BACKEND_TO_PROXY
            events = parse_all_sse_events(e.get("data", b""))
            if events:
                # Describe based on the most interesting event in the chunk
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

                # Summarize descriptions
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
        elif e["dir"] == 1:  # PROXY_TO_CLIENT
            desc = "Forwarded to client"

        # Highlight slow steps
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

    # Find all backend streaming sessions
    i = 0
    stream_num = 0
    while i < len(entries):
        e = entries[i]

        # Skip if backend filter doesn't match
        if backend_filter is not None and e.get("meta", {}).get("be") != backend_filter:
            i += 1
            continue

        # Look for PROXY_TO_BACKEND (start of request)
        if e["dir"] == 2:
            stream_num += 1
            print(f"\n--- Stream #{stream_num} (Entry [{e.get('seq')}]) ---")

            start_ts = e.get("ts", 0)

            # Collect backend response chunks
            chunks = []
            j = i + 1
            while j < len(entries) and entries[j]["dir"] != 2:  # Until next request
                if entries[j]["dir"] == 3:  # BACKEND_TO_PROXY
                    chunks.append(entries[j])
                j += 1

            if not chunks:
                print("  No backend response chunks")
                i = j
                continue

            # Calculate metrics
            ttft = chunks[0].get("ts", 0) - start_ts
            duration = chunks[-1].get("ts", 0) - start_ts
            chunk_count = len(chunks)
            total_bytes = sum(len(c.get("data", b"")) for c in chunks)

            print(f"  Time to First Token: {ttft:.3f}s")
            print(f"  Total Duration: {duration:.3f}s")
            print(f"  Chunks: {chunk_count}")
            print(f"  Total Data: {total_bytes:,} bytes")

            if chunk_count > 1:
                avg_chunk_time = duration / (chunk_count - 1)
                print(f"  Avg Time Between Chunks: {avg_chunk_time:.3f}s")

            # Detect slow chunks
            slow_chunks = []
            for k in range(1, len(chunks)):
                gap = chunks[k].get("ts", 0) - chunks[k - 1].get("ts", 0)
                if gap > 5:
                    slow_chunks.append((chunks[k].get("seq"), gap))

            if slow_chunks:
                print("  Slow Chunks Detected:")
                for seq, gap in slow_chunks:
                    print(f"    Entry [{seq}]: {gap:.1f}s gap")

            i = j
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
        backend = e.get("meta", {}).get("be", "")
        backend_str = f" | backend={backend}" if backend else ""
        session = e.get("meta", {}).get("sid", "")
        session_str = f" | session={session[:8]}" if session else ""

        print(
            f"\n[{seq}] {direction} | {len(data):,} bytes | ts={ts_str}{backend_str}{session_str}"
        )

        # Verbose metadata
        if verbose:
            meta = e.get("meta", {}).copy()
            # Remove already shown fields
            for key in ["be", "sid"]:
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
    if not show_last and not jump_to_entry and not context_around and not entry_range:
        if max_entries > 0 and len(filtered_entries) > len(display_entries):
            remaining = len(filtered_entries) - len(display_entries)
            print(
                f"\n... and {remaining} more entries (use --last to see final entries)"
            )


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

        # Skip if backend filter is set and doesn't match
        if backend_filter is not None and e.get("meta", {}).get("be") != backend_filter:
            i += 1
            continue

        if e["dir"] == 0:  # CLIENT_TO_PROXY (new request)
            request_num += 1
            print(f"\n--- REQUEST #{request_num} ---")

            # Parse request
            try:
                req = json.loads(e["data"].decode("utf-8"))
                model = req.get("model", "N/A")
                print(f"Model: {model}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                print("Model: (could not parse)")

            # Collect related entries
            j = i + 1
            backend_entries = []
            client_chunks = []
            while j < len(entries) and entries[j]["dir"] != 0:
                if entries[j]["dir"] == 3:  # BACKEND_TO_PROXY
                    backend_entries.append(entries[j])
                elif entries[j]["dir"] == 1:  # PROXY_TO_CLIENT
                    client_chunks.append(entries[j]["data"])
                j += 1

            # Analyze backend responses
            backend_content_len = 0
            backend_tool_calls = 0
            backend_tool_names = set()
            backend_models = set()
            issues = []

            # Timing
            if backend_entries:
                ttft = backend_entries[0]["ts"] - e["ts"]
                duration = backend_entries[-1]["ts"] - e["ts"]
                print(f"Timing: TTFT={ttft:.3f}s, Duration={duration:.3f}s")

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

            i = j
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
        entry_dict = {
            "seq": e.get("seq"),
            "direction": DIRECTION_NAMES.get(e["dir"], f"Unknown({e['dir']})"),
            "timestamp": e.get("ts"),
            "data_length": len(e.get("data", b"")),
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
    print_summary(header, entries)

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
            e for e in entries if e.get("meta", {}).get("sid") == args.session_id
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
        elif args.search:
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
