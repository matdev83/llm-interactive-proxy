"""Argument parser for the CBOR capture inspection tool."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.wire_capture.inspection.types import InspectCliConfig


def build_parser(
    *, description: str, epilog: str | None = None
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
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
        help=(
            "Filter entries after this time (Unix timestamp, ISO datetime, or time-only)"
        ),
    )
    parser.add_argument(
        "--end-time",
        metavar="TIME",
        help=(
            "Filter entries before this time (Unix timestamp, ISO datetime, or time-only)"
        ),
    )
    return parser


def config_from_args(args: argparse.Namespace) -> InspectCliConfig:
    return InspectCliConfig(
        capture_path=Path(args.capture_file),
        entries=args.entries,
        analyze=args.analyze,
        json_target=args.json,
        direction=args.direction,
        backend=args.backend,
        list_backends=args.list_backends,
        max_data=args.max_data,
        status_summary=args.status_summary,
        verbose=args.verbose,
        search=args.search,
        session_substring=args.session_substring,
        show_hex=args.hex,
        last=args.last,
        range_str=args.range,
        around=args.around,
        context=args.context,
        entry=args.entry,
        timeline=args.timeline,
        detect_issues=args.detect_issues,
        group_by_session=args.group_by_session,
        b2bua=args.b2bua,
        track_request=args.track_request,
        analyze_streaming=args.analyze_streaming,
        session_id=args.session_id,
        start_time=args.start_time,
        end_time=args.end_time,
    )


def parse_inspect_config(
    argv: list[str] | None, *, epilog: str | None = None
) -> InspectCliConfig:
    parser = build_parser(
        description="Inspect CBOR wire capture files for debugging",
        epilog=epilog,
    )
    args = parser.parse_args(argv)
    return config_from_args(args)
