"""Analyze CBOR capture for error responses."""
import sys
import zlib
import json
from pathlib import Path
sys.path.insert(0, '.')

import cbor2

# Direction mapping: 0=CLIENT_TO_PROXY, 1=PROXY_TO_CLIENT, 2=PROXY_TO_BACKEND, 3=BACKEND_TO_PROXY
DIRECTION_NAMES = {
    0: "CLIENT_TO_PROXY",
    1: "PROXY_TO_CLIENT",
    2: "PROXY_TO_BACKEND",
    3: "BACKEND_TO_PROXY",
}

def load_capture_file(path):
    """Load a CBOR capture file and return header and entries."""
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
    return header, entries

def parse_all_sse_events(data):
    """Parse all SSE data chunks in a payload into a list of JSON objects."""
    if not data:
        return []
    text = data.decode('utf-8', errors='replace').strip()

    results = []
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            json_str = line[6:].strip()
            if json_str and json_str != "[DONE]":
                try:
                    result = json.loads(json_str)
                    results.append(result)
                except json.JSONDecodeError:
                    continue
    return results

header, entries = load_capture_file('var/wire_captures_cbor/client-debug.cbor')

print(f"Total entries: {len(entries)}")
print()

# Find PROXY_TO_CLIENT entries with Forbidden/403 errors
error_entries = []
for i, entry in enumerate(entries):
    if entry.get("dir") == 1:  # PROXY_TO_CLIENT
        data = entry.get("data", b"")
        if isinstance(data, bytes):
            try:
                data = data.decode('utf-8', errors='replace')
            except:
                pass
        data_str = str(data)
        # Look specifically for Forbidden/403 errors
        if '403' in data_str or 'Forbidden' in data_str or '"status_code": 403' in data_str:
            error_entries.append((i, entry, data_str))

print(f"Found {len(error_entries)} PROXY_TO_CLIENT entries with Forbidden/403 errors")
print()

# Show first few
for idx, (i, entry, data_str) in enumerate(error_entries[:5]):
    print(f'[{i}] ts={entry.get("ts")} session={entry.get("meta", {}).get("sid", "N/A")}')
    print(f'    backend: {entry.get("meta", {}).get("be", "N/A")}')
    print(f'    data preview: {data_str[:1200]}')

    # Try to parse SSE
    events = parse_all_sse_events(entry.get("data", b""))
    if events:
        print(f'    Parsed SSE events:')
        for ev in events:
            if 'error' in ev:
                print(f'      ERROR: {json.dumps(ev["error"], indent=2)[:500]}')
    print()
