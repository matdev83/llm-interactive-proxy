"""Temporary script to analyze CBOR capture for tool call issues."""
import sys
sys.path.insert(0, '.')
from src.core.simulation.capture_reader import CaptureReader
import json

reader = CaptureReader()
session = reader.load('./var/wire_captures_cbor/0645d0f084dc4b2a8b023ab0de989a1b.cbor')

print("=" * 80)
print("EXAMINING ENTRIES 280-400 (AROUND PROBLEM AREA)")
print("=" * 80)

# Look at entries around the problem area
for i, entry in enumerate(session.entries):
    if i < 280 or i > 400:
        continue
    data = entry.data
    if isinstance(data, bytes):
        try:
            decoded = data.decode('utf-8')
        except:
            continue
    elif isinstance(data, str):
        decoded = data
    elif isinstance(data, dict):
        decoded = json.dumps(data)
    else:
        continue
    
    # Show entries with finish_reason or tool_calls
    if 'finish_reason' in decoded and 'null' not in decoded.split('finish_reason')[1][:10]:
        print(f'[{i}] {entry.direction.name}')
        print(f'  Length: {len(decoded)}')
        # Show the finish_reason and tool_calls portion
        if 'tool_calls' in decoded:
            # Extract the tool_calls portion
            start = decoded.find('"tool_calls"')
            if start != -1:
                snippet = decoded[start:start+500]
                print(f'  tool_calls portion: {snippet}')
        else:
            print(f'  NO TOOL_CALLS in this response')
            # Show what the content is
            if '"content"' in decoded:
                start = decoded.find('"content"')
                snippet = decoded[start:start+300]
                print(f'  content portion: {snippet}')
        print()

print("=" * 80)
print("BACKEND TO PROXY RESPONSES (WHAT BACKEND SENT)")
print("=" * 80)

for i, entry in enumerate(session.entries):
    if i < 280 or i > 400:
        continue
    if entry.direction.name != 'BACKEND_TO_PROXY':
        continue
    data = entry.data
    if isinstance(data, bytes):
        try:
            decoded = data.decode('utf-8')
        except:
            continue
    elif isinstance(data, str):
        decoded = data
    else:
        continue
    
    if len(decoded) > 100:  # Skip empty/small entries
        print(f'[{i}] B->P len={len(decoded)}')
        print(f'  preview: {decoded[:400]}')
        print()

