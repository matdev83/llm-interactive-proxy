"""
Script to detect dropped chunks in CBOR wire captures - improved version.

Groups consecutive B->P entries that arrive before a P->C.
"""

import sys
sys.path.insert(0, ".")

import cbor2
import json
from collections import defaultdict
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
    
    print("=" * 60)
    print("SEQUENTIAL ANALYSIS")
    print("=" * 60)
    
    # Look for patterns: consecutive B->P without P->C in between
    pending_bp = []
    dropped_groups = []
    
    for i, entry in enumerate(entries):
        direction = entry.get("direction", "")
        data = entry.get("data", b"")
        ts = entry.get("timestamp", 0)
        content = extract_content(data) if data else None
        
        if direction == "backend_to_proxy" and content is not None:
            pending_bp.append({
                "idx": i,
                "ts": ts,
                "content": content,
            })
        elif direction == "proxy_to_client" and content is not None:
            # Check if we have multiple pending B->P but only one P->C
            if len(pending_bp) > 1:
                # This P->C corresponds to how many B->P?
                dropped_groups.append({
                    "bp_entries": pending_bp.copy(),
                    "pc_idx": i,
                    "pc_content": content,
                    "pc_ts": ts,
                })
            pending_bp.clear()
    
    print(f"\nFound {len(dropped_groups)} groups where multiple B->P were followed by single P->C\n")
    
    for group in dropped_groups[:20]:  # Show first 20
        bp_entries = group["bp_entries"]
        print(f"B->P batch ({len(bp_entries)} entries):")
        for bp in bp_entries:
            print(f"  [{bp['idx']}] ts={bp['ts']:.6f} content={bp['content']!r}")
        print(f"P->C [{group['pc_idx']}] ts={group['pc_ts']:.6f} content={group['pc_content']!r}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python detect_dropped_chunks_v2.py <capture_file>")
        sys.exit(1)
    
    analyze_capture(sys.argv[1])

