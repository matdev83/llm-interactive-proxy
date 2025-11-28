#!/usr/bin/env python
"""Analyze CBOR capture for usage leaks."""
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

# Look for stop chunks being sent to client
print("\n=== STOP CHUNKS SENT TO CLIENT ===")
for i, e in enumerate(entries):
    if e.get("dir") == 2:  # PROXY_TO_CLIENT
        data = e.get("data", b"")
        if isinstance(data, bytes):
            data_str = data.decode("utf-8", errors="ignore")
        else:
            data_str = str(data)
        
        # Show all non-empty chunks sent to client
        if len(data_str) > 10:
            if len(data_str) < 2000:
                print(f"\nEntry {i} ({len(data_str)} bytes):")
                print(data_str)
            else:
                print(f"\nEntry {i} ({len(data_str)} bytes): [truncated]")
                # Find the stop chunk part
                idx = data_str.find("finish_reason")
                if idx > 0:
                    print("..." + data_str[max(0,idx-100):min(len(data_str),idx+300)] + "...")

