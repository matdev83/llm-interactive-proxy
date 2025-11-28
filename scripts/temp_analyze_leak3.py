#!/usr/bin/env python
"""Analyze CBOR capture - look at specific entries."""
import cbor2
import json
import sys

capture_file = sys.argv[1] if len(sys.argv) > 1 else "var/wire_captures_cbor/bcffe150746b4f22bb39b47fabb4d70f.cbor"

with open(capture_file, "rb") as f:
    decoder = cbor2.CBORDecoder(f)
    entries = []
    try:
        while True:
            entries.append(decoder.decode())
    except Exception:
        pass

print(f"Total entries: {len(entries)}")

# Look at specific entries
for idx in [1, 2, 5, 6, 7, 8]:
    e = entries[idx]
    direction = e.get("dir")
    data = e.get("data", b"")
    if isinstance(data, bytes):
        data_str = data.decode("utf-8", errors="ignore")
    else:
        data_str = str(data)
    
    DIR_NAMES = {0: "C->P", 1: "P->B", 2: "P->C", 3: "B->P"}
    dir_name = DIR_NAMES.get(direction, "???")
    
    print(f"\n=== Entry {idx} ({dir_name}, {len(data_str)} bytes) ===")
    
    # Show first 500 chars
    print("First 500 chars:")
    print(data_str[:500])
    
    # If it's a big message, look for usage
    if "usage" in data_str or "prompt_tokens" in data_str:
        idx_usage = data_str.find("prompt_tokens")
        if idx_usage > 0:
            print("\n...around usage...")
            print(data_str[max(0, idx_usage-200):idx_usage+200])

