#!/usr/bin/env python
"""Analyze tool call duplication in CBOR capture."""
from pathlib import Path
import cbor2
import json

capture_path = Path("var/wire_captures_cbor/client-debug.cbor")

# Load capture
with capture_path.open("rb") as f:
    capture = cbor2.load(f)

entries = capture.get("entries", [])

# We'll collect tool calls from BACKEND_TO_PROXY entries, for session starting with "7a1a542f"
tool_calls = []  # list of (entry_seq, tool_name, arguments, signature)

# We need to parse the JSON body of each entry.
# For BACKEND_TO_PROXY entries, the data is a JSON with "choices" array, delta or full message.
# Tool calls are in choices[].delta.tool_calls or choices[].message.tool_calls depending on streaming/final.

def extract_tool_calls_from_parsed(parsed):
    """Extract tool calls from a parsed response dict."""
    tool_calls_found = []
    choices = parsed.get("choices", [])
    for choice in choices:
        # Check for delta (streaming)
        delta = choice.get("delta", {})
        if "tool_calls" in delta:
            for tc in delta["tool_calls"]:
                func = tc.get("function", {})
                name = func.get("name")
                args = func.get("arguments")
                if name:
                    tool_calls_found.append((name, args))
        # Check for message (non-streaming final, but sometimes tool_calls are in message)
        message = choice.get("message", {})
        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                func = tc.get("function", {})
                name = func.get("name")
                args = func.get("arguments")
                if name:
                    tool_calls_found.append((name, args))
    return tool_calls_found

for entry in entries:
    direction = entry.get("direction")
    if direction != "BACKEND_TO_PROXY":
        continue
    session_id = entry.get("metadata", {}).get("session_id", "")
    if not session_id.startswith("7a1a542f"):
        continue
    seq = entry.get("seq")
    parsed = entry.get("parsed")
    if not parsed:
        continue
    calls = extract_tool_calls_from_parsed(parsed)
    for name, args in calls:
        # Build a simple signature: if args is dict, we can create a stable representation; but for deduplication,
        # the system uses name+arguments_content hash. We'll just store the raw args for inspection.
        tool_calls.append({
            "seq": seq,
            "tool": name,
            "args": args,
            "timestamp": entry.get("timestamp")
        })

# Now group by tool name and examine reads
reads = [tc for tc in tool_calls if tc["tool"] == "read"]

print(f"Total tool calls in session 7a1a542f: {len(tool_calls)}")
print(f"Total read tool calls: {len(reads)}")

# Show arguments for each read call, in order
for i, r in enumerate(reads):
    print(f"\nRead #{i+1} (seq={r['seq']}, ts={r['timestamp']}):")
    print(f"  args = {r['args']}")

# Check for duplicate arguments (exact same)
arg_set = set()
dups = []
for r in reads:
    args_repr = json.dumps(r["args"], sort_keys=True) if isinstance(r["args"], (dict, list)) else str(r["args"])
    if args_repr in arg_set:
        dups.append(r)
    else:
        arg_set.add(args_repr)

if dups:
    print(f"\nFound {len(dups)} duplicate read calls (exact same arguments).")
else:
    print("\nNo duplicate read calls detected (all have distinct arguments).")
