import sys
from pathlib import Path

sys.path.insert(0, ".")
from scripts.inspect_cbor_capture import load_capture_file, print_entries

capture_file = Path("var/wire_captures_cbor/proxy-20251201_1834.cbor")
header, entries = load_capture_file(capture_file)

print(f"Total entries: {len(entries)}")
start_index = max(0, len(entries) - 20)
print(f"Showing entries from {start_index} to {len(entries)}")

print_entries(entries[start_index:], max_entries=20, verbose=False)
