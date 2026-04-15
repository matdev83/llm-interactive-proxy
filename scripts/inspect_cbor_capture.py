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

import sys
from pathlib import Path

# Repo root on sys.path so `import src.*` works when invoked as a file path.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.core.wire_capture.inspection.app import main

if __name__ == "__main__":
    raise SystemExit(main(epilog=__doc__))
