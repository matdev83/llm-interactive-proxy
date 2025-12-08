"""
Script to detect dropped chunks in CBOR wire captures.

Analyzes B->P and P->C entries to find cases where B->P chunks don't have
corresponding P->C entries.
"""

import sys
sys.path.insert(0, ".")

import cbor2
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def load_capture(filepath: str) -> list[dict]:
    """Load and parse CBOR capture file."""
    with open(filepath, "rb") as f:
        data = cbor2.load(f)
    return data.get("entries", [])


def extract_content(data: bytes) -> str | None:
    """Extract content from SSE data bytes."""
    try:
        text = data.decode("utf-8").strip()
        if not text.startswith("data:"):
            return None
        json_str = text[5:].strip()
        if json_str == "[DONE]":
            return "[DONE]"
        parsed = json.loads(json_str)
        choices = parsed.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            return delta.get("content", None)
    except Exception:
        return None


def analyze_capture(filepath: str):
    """Analyze capture for dropped chunks."""
    entries = load_capture(filepath)
    
    # Group entries by timestamp (microsecond precision)
    by_timestamp = defaultdict(list)
    
    for i, entry in enumerate(entries):
        ts = entry.get("timestamp", 0)
        direction = entry.get("direction", "")
        data = entry.get("data", b"")
        
        # Convert timestamp to microsecond string
        ts_us = f"{ts:.6f}"
        
        by_timestamp[ts_us].append({
            "idx": i,
            "direction": direction,
            "data": data,
            "content": extract_content(data) if data else None,
        })
    
    # Find timestamps where B->P count differs from P->C count
    print("=" * 60)
    print("DROPPED CHUNK ANALYSIS")
    print("=" * 60)
    
    dropped_count = 0
    
    for ts, entries_at_ts in sorted(by_timestamp.items()):
        bp_entries = [e for e in entries_at_ts if e["direction"] == "backend_to_proxy"]
        pc_entries = [e for e in entries_at_ts if e["direction"] == "proxy_to_client"]
        
        # Skip stream markers (empty data)
        bp_content = [e for e in bp_entries if e["data"] and e["content"] is not None]
        pc_content = [e for e in pc_entries if e["data"] and e["content"] is not None]
        
        if len(bp_content) > len(pc_content):
            dropped_count += 1
            print(f"\nTimestamp: {ts}")
            print(f"  B->P entries: {len(bp_content)}")
            print(f"  P->C entries: {len(pc_content)}")
            print(f"  B->P contents:")
            for e in bp_content:
                print(f"    [{e['idx']}] {e['content']!r}")
            print(f"  P->C contents:")
            for e in pc_content:
                print(f"    [{e['idx']}] {e['content']!r}")
    
    print(f"\n{'=' * 60}")
    print(f"Total timestamps with dropped chunks: {dropped_count}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python detect_dropped_chunks.py <capture_file>")
        sys.exit(1)
    
    analyze_capture(sys.argv[1])

