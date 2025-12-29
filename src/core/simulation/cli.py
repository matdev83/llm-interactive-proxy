"""
CLI for capture replay and simulation.

Usage:
    python -m src.core.simulation.cli replay --capture path/to/capture.cbor [options]
    python -m src.core.simulation.cli inspect --capture path/to/capture.cbor
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from src.core.simulation.capture_reader import (
    CaptureReader,
)
from src.core.simulation.output_utils import (
    configure_console_encoding,
    console_print,
    safe_bytes_preview,
    safe_str,
)
from src.core.simulation.simulation_runner import (
    SimulationRunner,
    create_simulation_report,
)

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Set up logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_replay(args: argparse.Namespace) -> int:
    """Run capture replay against a proxy.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    capture_path = Path(args.capture)
    if not capture_path.exists():
        console_print(f"Error: Capture file not found: {capture_path}", file=sys.stderr)
        return 1

    runner = SimulationRunner(
        proxy_base_url=args.proxy_url,
        timing_tolerance_ms=args.timing_tolerance,
        speed_multiplier=args.speed,
    )

    console_print(f"Replaying capture: {capture_path}")
    console_print(f"Target proxy: {args.proxy_url}")
    console_print(f"Speed: {args.speed}x")
    console_print()

    try:
        result = asyncio.run(runner.run(capture_path))
    except Exception as e:
        console_print(f"Error during replay: {e}", file=sys.stderr)
        return 1

    # Print summary (may contain Unicode from captured data)
    console_print(safe_str(result.summary))
    console_print()

    # Write report if requested
    if args.report:
        report_path = Path(args.report)
        if args.json:
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
            console_print(f"JSON report written to: {report_path}")
        else:
            report = create_simulation_report([result])
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(report)
            console_print(f"Report written to: {report_path}")

    return 0 if result.success else 1


def cmd_inspect(args: argparse.Namespace) -> int:
    """Inspect a capture file and print summary.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    capture_path = Path(args.capture)
    if not capture_path.exists():
        console_print(f"Error: Capture file not found: {capture_path}", file=sys.stderr)
        return 1

    reader = CaptureReader()
    try:
        session = reader.load(capture_path)
    except Exception as e:
        console_print(f"Error loading capture: {e}", file=sys.stderr)
        return 1

    summary = reader.summarize()

    console_print(f"Capture File: {capture_path}")
    console_print(f"Session ID: {safe_str(str(summary.session_id))}")
    console_print(f"Created At: {summary.created_at}")
    console_print()
    console_print("Statistics:")
    console_print(f"  Total Entries: {summary.total_entries}")
    console_print(f"  Total Bytes: {summary.total_bytes}")
    console_print(f"  Duration: {summary.duration_seconds:.2f}s")
    console_print(f"  Streams: {summary.stream_count}")
    console_print()
    console_print("Direction Counts:")
    direction_counts = summary.direction_counts
    console_print(f"  client_to_proxy: {direction_counts.client_to_proxy}")
    console_print(f"  proxy_to_client: {direction_counts.proxy_to_client}")
    console_print(f"  proxy_to_backend: {direction_counts.proxy_to_backend}")
    console_print(f"  backend_to_proxy: {direction_counts.backend_to_proxy}")
    console_print()
    console_print("Timing:")
    console_print(f"  Min Delta: {summary.min_timing_delta:.4f}s")
    console_print(f"  Max Delta: {summary.max_timing_delta:.4f}s")
    console_print(f"  Avg Delta: {summary.avg_timing_delta:.4f}s")

    if args.json:
        console_print()
        console_print("JSON Summary:")
        # Use ensure_ascii=True for console output to avoid encoding issues
        console_print(
            json.dumps(
                summary.model_dump(mode="python"),
                indent=2,
                default=str,
                ensure_ascii=True,
            )
        )

    if args.entries:
        console_print()
        console_print("Entries:")
        for i, entry in enumerate(session.entries[: args.entries]):
            # Use safe_bytes_preview for data preview
            data_preview = safe_bytes_preview(entry.data, max_length=50)
            console_print(
                f"  [{i}] seq={entry.sequence} dir={entry.direction.name} "
                f"ts={entry.timestamp:.4f} bytes={len(entry.data)} "
                f"data={data_preview!r}..."
            )
        if len(session.entries) > args.entries:
            console_print(
                f"  ... and {len(session.entries) - args.entries} more entries"
            )

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List capture files in a directory.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    capture_dir = Path(args.directory)
    if not capture_dir.exists():
        console_print(f"Error: Directory not found: {capture_dir}", file=sys.stderr)
        return 1

    capture_files = list(capture_dir.glob("*.cbor"))
    if not capture_files:
        console_print(f"No capture files found in: {capture_dir}")
        return 0

    console_print(f"Capture files in {capture_dir}:")
    console_print()

    reader = CaptureReader()
    for path in sorted(capture_files):
        try:
            reader.load(path)
            summary = reader.summarize()
            session_id = safe_str(str(summary.session_id))
            console_print(
                f"  {path.name}: {summary.total_entries} entries, "
                f"{summary.total_bytes} bytes, "
                f"session={session_id}"
            )
        except Exception as e:
            console_print(f"  {path.name}: ERROR - {e}")

    return 0


def main() -> int:
    """Main entry point for the CLI."""
    # Configure console encoding for Windows compatibility
    configure_console_encoding()

    parser = argparse.ArgumentParser(
        prog="simulation",
        description="Capture replay and simulation CLI for regression testing",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose logging"
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Replay command
    replay_parser = subparsers.add_parser(
        "replay", help="Replay a capture against a proxy"
    )
    replay_parser.add_argument(
        "--capture", "-c", required=True, help="Path to CBOR capture file"
    )
    replay_parser.add_argument(
        "--proxy-url",
        "-p",
        default="http://localhost:8000",
        help="Proxy URL (default: http://localhost:8000)",
    )
    replay_parser.add_argument(
        "--speed",
        "-s",
        type=float,
        default=1.0,
        help="Replay speed multiplier (default: 1.0 = realtime)",
    )
    replay_parser.add_argument(
        "--timing-tolerance",
        "-t",
        type=float,
        default=100.0,
        help="Timing tolerance in ms (default: 100.0)",
    )
    replay_parser.add_argument("--report", "-r", help="Write report to file")
    replay_parser.add_argument(
        "--json", "-j", action="store_true", help="Output report in JSON format"
    )
    replay_parser.set_defaults(func=cmd_replay)

    # Inspect command
    inspect_parser = subparsers.add_parser("inspect", help="Inspect a capture file")
    inspect_parser.add_argument(
        "--capture", "-c", required=True, help="Path to CBOR capture file"
    )
    inspect_parser.add_argument(
        "--json", "-j", action="store_true", help="Output summary in JSON format"
    )
    inspect_parser.add_argument(
        "--entries",
        "-e",
        type=int,
        default=0,
        help="Show first N entries (default: 0 = none)",
    )
    inspect_parser.set_defaults(func=cmd_inspect)

    # List command
    list_parser = subparsers.add_parser(
        "list", help="List capture files in a directory"
    )
    list_parser.add_argument(
        "--directory", "-d", default=".", help="Directory to scan (default: .)"
    )
    list_parser.set_defaults(func=cmd_list)

    args = parser.parse_args()

    if args.verbose:
        setup_logging(verbose=True)
    else:
        setup_logging(verbose=False)

    if not args.command:
        parser.print_help()
        return 0

    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
