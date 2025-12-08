#!/usr/bin/env python3
"""Test SSE decoding."""

import json

# Simulate what _decode_sse_payload does when content is SSE-formatted string
sse_data = 'data: {"choices": [{"delta": {"content": "\\n", "role": "assistant"}, "finish_reason": null}], "id": "test", "model": "test", "created": 12345}'

print(f"Input SSE data: {sse_data}")

# This is the _decode_sse_payload logic
text_payload = sse_data
stripped = text_payload.strip()
if "data:" not in stripped:
    print("No data: found")
else:
    data_lines = []
    for line in stripped.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    
    data_body = "\n".join(data_lines).strip()
    print(f"data_body: {data_body}")
    
    decoded = json.loads(data_body)
    print(f"decoded: {decoded}")
    print(f"delta content: {repr(decoded['choices'][0]['delta']['content'])}")

