"""
Script to find specific newline chunks that are missing from P->C.
"""

import sys

sys.path.insert(0, ".")

import json
from typing import Any, cast

import cbor2


def load_capture(filepath: str) -> list[dict[str, Any]]:
    """Load and parse CBOR capture file."""
    with open(filepath, "rb") as f:
        loaded = cbor2.load(f)
    data = cast(dict[str, Any], loaded)
    entries = data.get("entries", [])
    if isinstance(entries, list):
        return cast(list[dict[str, Any]], entries)
    return []


def extract_content(data: bytes) -> str | None:
    """Extract content from SSE data bytes."""
    try:
        text = data.decode("utf-8").strip()
        if not text.startswith("data:"):
            return None
        json_str = text[5:].strip()
        if json_str == "[DONE]":
            return "[DONE]"
        parsed = cast(dict[str, Any], json.loads(json_str))
        choices = parsed.get("choices", [])
        if choices:
            delta = cast(dict[str, Any], choices[0].get("delta", {}))
            content = delta.get("content", None)
            return content if isinstance(content, str) else None
    except Exception:
        return None
    return None


def analyze_capture(filepath: str) -> None:
    """Analyze capture for dropped whitespace chunks."""
    entries = load_capture(filepath)

    print("=" * 60)
    print("WHITESPACE CHUNK ANALYSIS")
    print("=" * 60)

    # Find all B->P entries with whitespace-only content
    bp_whitespace = []
    for i, entry in enumerate(entries):
        direction = entry.get("direction", "")
        data = entry.get("data", b"")
        ts = entry.get("timestamp", 0)
        content = extract_content(data) if data else None

        # Check if content is whitespace-only (but not empty)
        if direction == "backend_to_proxy" and content and content.strip() == "":
            bp_whitespace.append(
                {
                    "idx": i,
                    "ts": ts,
                    "content": content,
                }
            )

    print(f"\nFound {len(bp_whitespace)} B->P entries with whitespace-only content\n")

    for bp in bp_whitespace:
        print(f"[{bp['idx']}] ts={bp['ts']:.6f} content={bp['content']!r}")

    # Now check surrounding entries
    print(f"\n{'=' * 60}")
    print("CHECKING SURROUNDING P->C FOR EACH WHITESPACE B->P")
    print("=" * 60)

    for bp in bp_whitespace[:10]:  # Check first 10
        bp_idx = bp["idx"]
        print(f"\nB->P [{bp_idx}] content={bp['content']!r}")

        # Look for P->C entries around this index
        for j in range(max(0, bp_idx - 3), min(len(entries), bp_idx + 5)):
            entry = entries[j]
            direction = entry.get("direction", "")
            data = entry.get("data", b"")
            ts = entry.get("timestamp", 0)
            content = extract_content(data) if data else None

            if content is not None:
                marker = "<<<" if j == bp_idx else ""
                print(
                    f"  [{j}] {direction[:4]:<4} ts={ts:.6f} content={content!r} {marker}"
                )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python detect_dropped_chunks_v3.py <capture_file>")
        sys.exit(1)

    analyze_capture(sys.argv[1])
