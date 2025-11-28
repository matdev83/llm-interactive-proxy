#!/usr/bin/env python
"""Debug capture directions."""
import cbor2
from collections import Counter

capture_file = "var/wire_captures_cbor/bcffe150746b4f22bb39b47fabb4d70f.cbor"

with open(capture_file, "rb") as f:
    decoder = cbor2.CBORDecoder(f)
    entries = []
    try:
        while True:
            entries.append(decoder.decode())
    except Exception:
        pass

print(f"Total entries: {len(entries)}")

# Check actual direction values (dir=X where X is numeric or string)
dir_values = []
for e in entries:
    d = e.get("dir")
    dir_values.append(d)

print(f"\nUnique direction values: {set(dir_values)}")
print(f"Direction counts: {Counter(dir_values)}")

# Check the meta field for direction info
print("\n=== SAMPLE ENTRY METADATA ===")
for i in [0, 1, 2, 5, 6, 7, 8]:
    if i < len(entries):
        e = entries[i]
        meta = e.get("meta", {})
        print(f"Entry {i}: dir={e.get('dir')}, meta.direction={meta.get('direction')}, meta.backend={meta.get('backend')}")
        data = e.get("data", b"")
        if isinstance(data, bytes):
            data_str = data.decode("utf-8", errors="ignore")[:100]
        else:
            data_str = str(data)[:100]
        print(f"          data preview: {data_str}")

