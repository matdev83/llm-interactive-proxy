"""CBOR wire capture inspection (library API and CLI backing)."""

from __future__ import annotations

from src.core.wire_capture.inspection.analysis_pairs import (
    analyze_request_response_pairs,
)
from src.core.wire_capture.inspection.analysis_streaming import analyze_streaming
from src.core.wire_capture.inspection.analysis_track import track_request
from src.core.wire_capture.inspection.app import main, run, run_inspection
from src.core.wire_capture.inspection.export_json import export_to_json
from src.core.wire_capture.inspection.filters import (
    filter_entries_by_backend,
    filter_entries_by_time,
    format_timestamp,
    get_unique_backends,
    parse_entry_range,
    parse_time_arg,
)
from src.core.wire_capture.inspection.issues import detect_issues
from src.core.wire_capture.inspection.loader import load_capture_file
from src.core.wire_capture.inspection.metadata import normalize_metadata
from src.core.wire_capture.inspection.payload import (
    parse_all_sse_events,
    parse_sse_chunk,
)
from src.core.wire_capture.inspection.render_console import (
    print_entries,
    print_summary,
    print_timeline,
)
from src.core.wire_capture.inspection.types import InspectCliConfig

__all__ = [
    "InspectCliConfig",
    "analyze_request_response_pairs",
    "analyze_streaming",
    "detect_issues",
    "filter_entries_by_backend",
    "filter_entries_by_time",
    "format_timestamp",
    "get_unique_backends",
    "export_to_json",
    "load_capture_file",
    "main",
    "normalize_metadata",
    "parse_all_sse_events",
    "parse_entry_range",
    "parse_sse_chunk",
    "parse_time_arg",
    "print_entries",
    "print_summary",
    "print_timeline",
    "run",
    "run_inspection",
    "track_request",
]
