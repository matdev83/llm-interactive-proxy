#!/usr/bin/env python
"""Analyze CBOR capture - look at actual SSE chunks sent to client."""
import cbor2
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

# Map direction numbers to names
DIR_NAMES = {0: "C->P", 1: "P->B", 2: "P->C", 3: "B->P"}

# Check entry structure
print("\n=== SAMPLE ENTRY STRUCTURE ===")
if entries:
    e = entries[5]
    print(f"Keys: {e.keys()}")
    print(f"Entry 5: dir={e.get('dir')}, data type={type(e.get('data'))}")
    
# Count by direction
from collections import Counter
dir_counts = Counter(e.get("dir") for e in entries)
print(f"\nDirection counts: {dir_counts}")

# Find first response (small PROXY_TO_CLIENT entries after a CLIENT_TO_PROXY)
print("\n=== FIRST RESPONSE CHUNKS (PROXY_TO_CLIENT) ===")
response_chunks = []
for i, e in enumerate(entries[:200]):
    direction = e.get("dir")
    data = e.get("data", b"")
    
    # Debug
    if i < 20:
        size = len(data) if isinstance(data, (bytes, str)) else len(str(data))
        print(f"  Entry {i}: dir={direction}, size={size}")
    
    if isinstance(data, bytes):
        data_str = data.decode("utf-8", errors="ignore")
    else:
        data_str = str(data)
    
    # Look for small P->C entries (SSE chunks)
    if direction == 2 and 10 < len(data_str) < 2000:
        print(f"\nEntry {i} ({len(data_str)} bytes):")
        print(data_str[:800])
        response_chunks.append(i)
        
    if len(response_chunks) > 10:
        break

