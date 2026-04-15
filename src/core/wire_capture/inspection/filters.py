"""Filter and summarize capture entries."""

from __future__ import annotations

import datetime
from typing import Any

from src.core.wire_capture.inspection.metadata import meta_a_session_id


def format_timestamp(ts: float) -> str:
    """Format a timestamp into a human-readable string."""
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def parse_time_arg(time_str: str, reference_date: datetime.date | None = None) -> float:
    """Parse a time argument into a Unix timestamp."""
    time_str = time_str.strip()

    try:
        ts = float(time_str)
        if ts > 0:
            return ts
    except ValueError:
        pass

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
    """Filter entries by time range."""
    if start_time is None and end_time is None:
        return entries

    result: list[dict[str, Any]] = []
    for e in entries:
        ts = e.get("ts", 0)
        if start_time is not None and ts < start_time:
            continue
        if end_time is not None and ts > end_time:
            continue
        result.append(e)
    return result


def get_unique_backends(entries: list[dict[str, Any]]) -> dict[str, int]:
    """Extract unique backends from capture entries with their counts."""
    backend_counts: dict[str, int] = {}
    for e in entries:
        meta = e.get("meta", {})
        backend = meta.get("be")
        if backend:
            backend_counts[backend] = backend_counts.get(backend, 0) + 1

    return dict(sorted(backend_counts.items(), key=lambda x: x[1], reverse=True))


def filter_entries_by_backend(
    entries: list[dict[str, Any]], backend_name: str | None
) -> list[dict[str, Any]]:
    """Filter entries by backend name."""
    if backend_name is None:
        return entries

    return [e for e in entries if e.get("meta", {}).get("be") == backend_name]


def get_unique_sessions(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Extract unique session IDs from capture entries with metadata."""
    sessions: dict[str, dict[str, Any]] = {}
    for e in entries:
        meta = e.get("meta", {})
        sid = meta_a_session_id(meta)
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
