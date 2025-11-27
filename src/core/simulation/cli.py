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

from src.core.simulation.capture_reader import CaptureReader
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
        print(f"Error: Capture file not found: {capture_path}", file=sys.stderr)
        return 1

    runner = SimulationRunner(
        proxy_base_url=args.proxy_url,
        timing_tolerance_ms=args.timing_tolerance,
        speed_multiplier=args.speed,
    )

    print(f"Replaying capture: {capture_path}")
    print(f"Target proxy: {args.proxy_url}")
    print(f"Speed: {args.speed}x")
    print()

    try:
        result = asyncio.run(runner.run(capture_path))
    except Exception as e:
        print(f"Error during replay: {e}", file=sys.stderr)
        return 1

    # Print summary
    print(result.summary)
    print()

    # Write report if requested
    if args.report:
        report_path = Path(args.report)
        if args.json:
            with open(report_path, "w") as f:
                json.dump(result.to_dict(), f, indent=2)
            print(f"JSON report written to: {report_path}")
        else:
            report = create_simulation_report([result])
            with open(report_path, "w") as f:
                f.write(report)
            print(f"Report written to: {report_path}")

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
        print(f"Error: Capture file not found: {capture_path}", file=sys.stderr)
        return 1

    reader = CaptureReader()
    try:
        session = reader.load(capture_path)
    except Exception as e:
        print(f"Error loading capture: {e}", file=sys.stderr)
        return 1

    summary = reader.summarize()

    print(f"Capture File: {capture_path}")
    print(f"Session ID: {summary['session_id']}")
    print(f"Created At: {summary['created_at']}")
    print()
    print("Statistics:")
    print(f"  Total Entries: {summary['total_entries']}")
    print(f"  Total Bytes: {summary['total_bytes']}")
    print(f"  Duration: {summary['duration_seconds']:.2f}s")
    print(f"  Streams: {summary['stream_count']}")
    print()
    print("Direction Counts:")
    direction_counts = summary.get("direction_counts", {})
    if isinstance(direction_counts, dict):
        for direction, count in direction_counts.items():
            print(f"  {direction}: {count}")
    print()
    print("Timing:")
    print(f"  Min Delta: {summary['min_timing_delta']:.4f}s")
    print(f"  Max Delta: {summary['max_timing_delta']:.4f}s")
    print(f"  Avg Delta: {summary['avg_timing_delta']:.4f}s")

    if args.json:
        print()
        print("JSON Summary:")
        print(json.dumps(summary, indent=2, default=str))

    if args.entries:
        print()
        print("Entries:")
        for i, entry in enumerate(session.entries[: args.entries]):
            data_preview = entry.data[:50].decode("utf-8", errors="replace")
            print(
                f"  [{i}] seq={entry.sequence} dir={entry.direction.name} "
                f"ts={entry.timestamp:.4f} bytes={len(entry.data)} "
                f"data={data_preview!r}..."
            )
        if len(session.entries) > args.entries:
            print(f"  ... and {len(session.entries) - args.entries} more entries")

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
        print(f"Error: Directory not found: {capture_dir}", file=sys.stderr)
        return 1

    capture_files = list(capture_dir.glob("*.cbor"))
    if not capture_files:
        print(f"No capture files found in: {capture_dir}")
        return 0

    print(f"Capture files in {capture_dir}:")
    print()

    reader = CaptureReader()
    for path in sorted(capture_files):
        try:
            reader.load(path)
            summary = reader.summarize()
            print(
                f"  {path.name}: {summary['total_entries']} entries, "
                f"{summary['total_bytes']} bytes, "
                f"session={summary['session_id']}"
            )
        except Exception as e:
            print(f"  {path.name}: ERROR - {e}")

    return 0


def main() -> int:
    """Main entry point for the CLI."""
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
