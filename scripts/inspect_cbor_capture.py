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

    # Show first 10 entries with full data
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --entries 10

    # Analyze request/response pairs
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --analyze

    # Export to JSON for further processing
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --json > output.json

    # Filter by direction
    python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --direction backend_to_proxy
"""

from __future__ import annotations

import argparse
import json
import sys
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


def parse_sse_chunk(data: bytes) -> dict[str, Any] | None:
    """Parse an SSE data chunk into JSON if valid.

    SSE chunks may contain multiple events separated by blank lines.
    This function parses the first non-[DONE] JSON event.
    """
    if not data:
        return None
    text = data.decode("utf-8", errors="replace").strip()

    # SSE format: events are separated by blank lines
    # Each event line starts with "data: "
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            json_str = line[6:].strip()
            if json_str and json_str != "[DONE]":
                try:
                    result: dict[str, Any] = json.loads(json_str)
                    return result
                except json.JSONDecodeError:
                    continue  # Try next line
    return None


def load_capture_file(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Load a CBOR capture file and return header and entries."""
    entries = []
    with open(path, "rb") as f:
        header = cbor2.load(f)
        while True:
            try:
                entries.append(cbor2.load(f))
            except EOFError:
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


def print_entries(
    entries: list[dict[str, Any]],
    max_entries: int = 20,
    max_data_length: int = 200,
    direction_filter: int | None = None,
) -> None:
    """Print individual entries."""
    print()
    print("=" * 70)
    print("ENTRIES")
    print("=" * 70)

    count = 0
    for i, e in enumerate(entries):
        if direction_filter is not None and e["dir"] != direction_filter:
            continue

        if count >= max_entries:
            remaining = sum(
                1
                for x in entries[i:]
                if direction_filter is None or x["dir"] == direction_filter
            )
            print(f"\n... and {remaining} more entries")
            break

        count += 1
        direction = DIRECTION_SYMBOLS.get(e["dir"], f"?{e['dir']}")
        data = e.get("data", b"")
        seq = e.get("seq", "?")
        ts = e.get("ts", 0)

        print(f"\n[{seq}] {direction} | {len(data):,} bytes | ts={ts:.4f}")

        if data:
            preview = safe_decode(data, max_data_length)
            # Indent the preview
            for line in preview.split("\n")[:5]:
                print(f"    {line}")
            if len(data) > max_data_length:
                print(f"    ... ({len(data) - max_data_length} more bytes)")


def analyze_request_response_pairs(entries: list[dict[str, Any]]) -> None:
    """Analyze request/response pairs and detect issues."""
    print()
    print("=" * 70)
    print("REQUEST/RESPONSE ANALYSIS")
    print("=" * 70)

    request_num = 0
    i = 0

    while i < len(entries):
        e = entries[i]
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
            backend_chunks = []
            client_chunks = []
            while j < len(entries) and entries[j]["dir"] != 0:
                if entries[j]["dir"] == 3:  # BACKEND_TO_PROXY
                    backend_chunks.append(entries[j]["data"])
                elif entries[j]["dir"] == 1:  # PROXY_TO_CLIENT
                    client_chunks.append(entries[j]["data"])
                j += 1

            # Analyze backend responses
            backend_content_len = 0
            backend_models = set()
            issues = []

            for chunk in backend_chunks:
                parsed = parse_sse_chunk(chunk)
                if parsed:
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
                        backend_content_len += len(content)
                        if choice.get("finish_reason") == "stop" and not content:
                            issues.append("Immediate stop without content")

                    # Check for fallback
                    msg_id = parsed.get("id", "")
                    if "fallback" in msg_id:
                        issues.append("Fallback mechanism activated")

                    # Check for internal model names
                    if "code-assist" in model.lower():
                        issues.append(f"Internal model name leak: {model}")

            print(f"Backend models: {backend_models or 'N/A'}")
            print(f"Backend content: {backend_content_len} chars")

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
                parsed = parse_sse_chunk(chunk)
                if parsed:
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
    header: dict[str, Any], entries: list[dict[str, Any]], output_file: str | None
) -> None:
    """Export capture data to JSON format."""
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
        "--max-data",
        type=int,
        default=200,
        help="Maximum bytes of data to show per entry (default: 200)",
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

    # Handle JSON export
    if args.json:
        output_file = None if args.json == "-" else args.json
        export_to_json(header, entries, output_file)
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

    # Print entries if requested
    if args.entries > 0:
        print_entries(
            entries,
            max_entries=args.entries,
            max_data_length=args.max_data,
            direction_filter=direction_filter,
        )

    # Analyze if requested
    if args.analyze:
        analyze_request_response_pairs(entries)

    return 0


if __name__ == "__main__":
    sys.exit(main())
