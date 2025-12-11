"""
Analyze CBOR wire capture to examine PROXY_TO_BACKEND request payloads in detail.
"""

import json
import zlib
from pathlib import Path

import cbor2

# Direction constants
DIRECTION_PROXY_TO_BACKEND = 2


def main() -> None:
    path = Path("var/wire_captures_cbor/proxy-20251209_1017.cbor")
    if not path.exists():
        print(f"File not found: {path}")
        return

    # Load using same method as inspect script
    entries = []
    with open(path, "rb") as f:
        header = cbor2.load(f)
        while True:
            try:
                entry = cbor2.load(f)
                # Handle decompression
                if entry.get("enc") == "zlib":
                    entry["data"] = zlib.decompress(entry["data"])
                    del entry["enc"]
                entries.append(entry)
            except (EOFError, cbor2.CBORDecodeEOF):
                break

    print(f"Session ID: {header.get('session_id', 'N/A')}")
    print(f"Total entries: {len(entries)}")
    print()

    # Look at all PROXY_TO_BACKEND entries
    proxy_to_backend = [
        e for e in entries if e.get("dir") == DIRECTION_PROXY_TO_BACKEND
    ]
    print(f"Found {len(proxy_to_backend)} PROXY_TO_BACKEND entries")
    print("=" * 100)

    for i, entry in enumerate(proxy_to_backend):
        seq = entry.get("seq", i)
        meta = entry.get("meta", {})
        data = entry.get("data", b"")
        backend = meta.get("be", "N/A")
        session_id = meta.get("sid", "N/A")[:16] if meta.get("sid") else "N/A"

        print(f"\n[{seq}] Backend: {backend} | Session: {session_id}")
        print(f"Data size: {len(data)} bytes")

        if isinstance(data, bytes | bytearray):
            try:
                text = data.decode("utf-8", errors="ignore")
            except Exception:
                print("  (Could not decode)")
                continue
        elif isinstance(data, str):
            text = data
        else:
            print(f"  (Unexpected data type: {type(data)})")
            continue

        # Try to parse as JSON
        text = text.strip()
        if text.startswith("{"):
            try:
                obj = json.loads(text)
                # Print key fields
                print(f"  model: {obj.get('model', 'N/A')}")
                print(f"  stream: {obj.get('stream', '(NOT PRESENT)')}")
                print(f"  messages count: {len(obj.get('messages', []))}")

                # Show first 200 chars of the text
                preview = text[:300]
                if len(text) > 300:
                    preview += "..."
                print(f"  Preview: {preview}")
            except json.JSONDecodeError as e:
                print(f"  JSON parse error: {e}")
                print(f"  First 200 chars: {text[:200]}")
        else:
            print(f"  Not JSON. First 200 chars: {text[:200]}")

        print()


if __name__ == "__main__":
    main()
