#!/usr/bin/env python3
"""Test SSE decoding."""

import json


def decode_sse_payload(payload):
    """Simulate _decode_sse_payload from response_adapters.py"""
    text_payload = payload
    stripped = text_payload.strip()
    if "data:" not in stripped:
        return payload, {}, False

    data_lines = []
    for line in stripped.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())

    if not data_lines:
        return payload, {}, False

    data_body = "\n".join(data_lines).strip()
    if data_body in ("[DONE]", '["DONE"]'):
        return "", {"finish_reason": "stop"}, True

    try:
        decoded = json.loads(data_body)
    except json.JSONDecodeError:
        return data_body, {}, False

    return decoded, {}, False


# Simulate SSE data as it would come from backend
sse_data_newline = r'data: {"choices": [{"delta": {"role": "assistant", "content": "\n"}, "finish_reason": null}], "id": "gen-test", "model": "test", "created": 12345}'
sse_data_dash = r'data: {"choices": [{"delta": {"role": "assistant", "content": "-"}, "finish_reason": null}], "id": "gen-test", "model": "test", "created": 12345}'

# Test decoding
decoded1, meta1, done1 = decode_sse_payload(sse_data_newline)
decoded2, meta2, done2 = decode_sse_payload(sse_data_dash)

print("Newline chunk:")
print(f"  decoded: {decoded1}")
print(
    f"  delta.content: {repr(decoded1.get('choices', [{}])[0].get('delta', {}).get('content'))}"
)

print("\nDash chunk:")
print(f"  decoded: {decoded2}")
print(
    f"  delta.content: {repr(decoded2.get('choices', [{}])[0].get('delta', {}).get('content'))}"
)

