"""Orchestration entry point for CBOR capture inspection."""

from __future__ import annotations

import sys
from typing import TextIO

from src.core.wire_capture.inspection.analysis_pairs import (
    analyze_request_response_pairs,
)
from src.core.wire_capture.inspection.analysis_streaming import analyze_streaming
from src.core.wire_capture.inspection.analysis_track import track_request
from src.core.wire_capture.inspection.cli import build_parser, config_from_args
from src.core.wire_capture.inspection.export_json import export_to_json
from src.core.wire_capture.inspection.filters import (
    filter_entries_by_time,
    format_timestamp,
    get_unique_backends,
    parse_entry_range,
    parse_time_arg,
)
from src.core.wire_capture.inspection.issues import detect_issues
from src.core.wire_capture.inspection.loader import load_capture_file
from src.core.wire_capture.inspection.metadata import meta_a_session_id
from src.core.wire_capture.inspection.render_console import (
    group_by_session,
    print_b2bua_leg_summary,
    print_entries,
    print_issues_summary,
    print_summary,
    print_timeline,
)
from src.core.wire_capture.inspection.text_output import writeln
from src.core.wire_capture.inspection.types import InspectCliConfig


def run_inspection(
    cfg: InspectCliConfig,
    *,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run one inspection according to ``cfg``; return process exit code."""
    out = out or sys.stdout
    err = err or sys.stderr

    capture_path = cfg.capture_path
    if not capture_path.exists():
        writeln(err, f"Error: File not found: {capture_path}")
        return 1

    try:
        header, entries = load_capture_file(capture_path)
    except Exception as e:
        writeln(err, f"Error loading capture file: {e}")
        return 1

    backend_filter = cfg.backend

    if cfg.list_backends:
        backends = get_unique_backends(entries)
        if not backends:
            writeln(out, "No backend information available in this capture file")
        else:
            writeln(out, "=" * 70)
            writeln(out, "AVAILABLE BACKENDS")
            writeln(out, "=" * 70)
            for backend, count in backends.items():
                writeln(out, f"  {backend}: {count} entries")
        return 0

    if backend_filter:
        available_backends = get_unique_backends(entries)
        if backend_filter not in available_backends:
            writeln(
                err,
                f"Warning: Backend '{backend_filter}' not found in capture.",
            )
            if available_backends:
                backends_str = ", ".join(available_backends.keys())
                writeln(err, f"Available backends: {backends_str}")
            else:
                writeln(err, "No backend information available in this capture.")

    if cfg.json_target is not None:
        output_file = None if cfg.json_target == "-" else cfg.json_target
        export_to_json(
            header,
            entries,
            output_file,
            out=out,
            backend_filter=backend_filter,
        )
        return 0

    print_summary(header, entries, out=out, show_status_summary=cfg.status_summary)

    direction_filter = None
    if cfg.direction:
        direction_map = {
            "client_to_proxy": 0,
            "proxy_to_client": 1,
            "proxy_to_backend": 2,
            "backend_to_proxy": 3,
        }
        direction_filter = direction_map[cfg.direction]

    if cfg.session_id:
        entries = [
            e for e in entries if meta_a_session_id(e.get("meta", {})) == cfg.session_id
        ]
        if not entries:
            writeln(err, f"No entries found for session ID: {cfg.session_id}")
            return 1
        writeln(out, f"Filtered to session: {cfg.session_id}")
        writeln(out)

    start_time_f: float | None = None
    end_time_f: float | None = None
    if cfg.start_time:
        try:
            start_time_f = parse_time_arg(cfg.start_time)
        except ValueError as e:
            writeln(err, f"Error: {e}")
            return 1
    if cfg.end_time:
        try:
            end_time_f = parse_time_arg(cfg.end_time)
        except ValueError as e:
            writeln(err, f"Error: {e}")
            return 1

    if start_time_f is not None or end_time_f is not None:
        original_count = len(entries)
        entries = filter_entries_by_time(entries, start_time_f, end_time_f)
        if not entries:
            writeln(err, "No entries found in specified time range")
            return 1
        time_info: list[str] = []
        if start_time_f is not None:
            time_info.append(f"after {format_timestamp(start_time_f)}")
        if end_time_f is not None:
            time_info.append(f"before {format_timestamp(end_time_f)}")
        writeln(out, f"Filtered to entries {' and '.join(time_info)}")
        writeln(out, f"Matched {len(entries)} of {original_count} entries")
        writeln(out)

    entry_range = None
    if cfg.range_str:
        try:
            entry_range = parse_entry_range(cfg.range_str)
        except ValueError as e:
            writeln(err, f"Error: {e}")
            return 1

    if cfg.timeline:
        print_timeline(entries, out=out, backend_filter=backend_filter)

    if cfg.detect_issues:
        issues = detect_issues(entries)
        print_issues_summary(issues, out=out)

    if cfg.group_by_session:
        group_by_session(entries, out=out)

    if cfg.b2bua:
        print_b2bua_leg_summary(entries, out=out)

    if cfg.track_request is not None:
        track_request(
            entries,
            cfg.track_request,
            out=out,
            backend_filter=backend_filter,
        )

    if cfg.analyze_streaming:
        analyze_streaming(entries, out=out, backend_filter=backend_filter)

    show_entries = (
        cfg.entries > 0
        or cfg.search
        or cfg.session_substring
        or cfg.last is not None
        or cfg.range_str
        or cfg.around is not None
        or cfg.entry is not None
    )

    if show_entries:
        if cfg.last is not None:
            max_entries = cfg.last
        elif cfg.entries > 0:
            max_entries = cfg.entries
        elif cfg.search or cfg.session_substring:
            max_entries = len(entries)
        else:
            max_entries = 20

        print_entries(
            entries,
            out=out,
            max_entries=max_entries,
            max_data_length=cfg.max_data,
            direction_filter=direction_filter,
            backend_filter=backend_filter,
            verbose=cfg.verbose,
            search_term=cfg.search,
            session_substring=cfg.session_substring,
            show_hex=cfg.show_hex,
            entry_range=entry_range,
            show_last=cfg.last is not None,
            context_around=cfg.around,
            context_size=cfg.context,
            jump_to_entry=cfg.entry,
        )

    if cfg.analyze:
        analyze_request_response_pairs(entries, out=out, backend_filter=backend_filter)

    return 0


def main(argv: list[str] | None = None, *, epilog: str | None = None) -> int:
    """CLI entry: parse ``argv`` and run inspection."""
    parser = build_parser(
        description="Inspect CBOR wire capture files for debugging",
        epilog=epilog,
    )
    args = parser.parse_args(argv)
    cfg = config_from_args(args)
    return run_inspection(cfg)


def run(argv: list[str] | None, *, out: TextIO, err: TextIO, epilog: str | None) -> int:
    """Parse argv and run with explicit streams (for tests)."""
    parser = build_parser(
        description="Inspect CBOR wire capture files for debugging",
        epilog=epilog,
    )
    args = parser.parse_args(argv)
    cfg = config_from_args(args)
    return run_inspection(cfg, out=out, err=err)
