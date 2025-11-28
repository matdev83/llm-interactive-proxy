#!/usr/bin/env python
"""Show Entry 2 content."""
import cbor2
import json

capture_file = "var/wire_captures_cbor/bcffe150746b4f22bb39b47fabb4d70f.cbor"

with open(capture_file, "rb") as f:
    decoder = cbor2.CBORDecoder(f)
    entries = []
    try:
        while True:
            entries.append(decoder.decode())
    except Exception:
        pass

# Entry 2
e = entries[2]
data = e.get("data", b"")
if isinstance(data, bytes):
    data_str = data.decode("utf-8", errors="ignore")
else:
    data_str = str(data)

print(f"Entry 2 size: {len(data_str)} bytes")
print(f"Entry 2 dir: {e.get('dir')}")
print("\n=== STRUCTURE ===")
# Try to parse as JSON
try:
    parsed = json.loads(data_str)
    print(f"Top-level keys: {parsed.keys()}")
    if "messages" in parsed:
        print(f"Number of messages: {len(parsed['messages'])}")
        # Show last few messages
        for i, msg in enumerate(parsed["messages"][-3:]):
            role = msg.get("role")
            content = msg.get("content", "")
            if isinstance(content, str):
                content_preview = content[:200] if len(content) > 200 else content
            else:
                content_preview = str(content)[:200]
            print(f"\nMessage {len(parsed['messages'])-3+i}: role={role}")
            print(f"  content: {content_preview}")
except json.JSONDecodeError as ex:
    print(f"Not valid JSON: {ex}")
    print(f"First 1000 chars: {data_str[:1000]}")

