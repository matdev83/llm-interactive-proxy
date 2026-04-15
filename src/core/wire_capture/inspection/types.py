"""CLI configuration for CBOR capture inspection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class InspectCliConfig:
    """Resolved CLI options for a single inspection run."""

    capture_path: Path
    entries: int = 0
    analyze: bool = False
    json_target: str | None = None
    direction: str | None = None
    backend: str | None = None
    list_backends: bool = False
    max_data: int = 200
    status_summary: bool = False
    verbose: bool = False
    search: str | None = None
    session_substring: str | None = None
    show_hex: bool = False
    last: int | None = None
    range_str: str | None = None
    around: int | None = None
    context: int = 5
    entry: int | None = None
    timeline: bool = False
    detect_issues: bool = False
    group_by_session: bool = False
    b2bua: bool = False
    track_request: int | None = None
    analyze_streaming: bool = False
    session_id: str | None = None
    start_time: str | None = None
    end_time: str | None = None
