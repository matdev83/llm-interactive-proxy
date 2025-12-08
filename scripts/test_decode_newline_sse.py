"""Test SSE decoding of the actual newline bytes from the capture."""

import sys
sys.path.insert(0, ".")

import json

# Exact bytes from B->P entry [1219]
newline_sse = b'data: {"choices": [{"delta": {"role": "assistant", "content": "\\n"}, "finish_reason": null}], "id": "gen-1765213513-eNSJ347VpQI4YVBtRgOj", "model": "x-ai/grok-code-fast-1", "created": 1765213513}\n\n'

# Exact bytes from B->P entry [1220]
dash_sse = b'data: {"choices": [{"delta": {"role": "assistant", "content": "-"}, "finish_reason": null}], "id": "gen-1765213513-eNSJ347VpQI4YVBtRgOj", "model": "x-ai/grok-code-fast-1", "created": 1765213513}\n\n'


def decode_sse_payload(payload: bytes):
    """Simulating _decode_sse_payload from response_adapters.py"""
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload, {}, False
    
    stripped = text.strip()
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
    except json.JSONDecodeError as e:
        print(f"JSON decode error: {e}")
        return data_body, {}, False
    
    return decoded, {}, False


print("Testing SSE decoding:")
print("=" * 60)

for label, sse in [("Newline", newline_sse), ("Dash", dash_sse)]:
    decoded, meta, is_done = decode_sse_payload(sse)
    print(f"\n{label} chunk:")
    print(f"  Decoded type: {type(decoded)}")
    print(f"  is_done: {is_done}")
    
    if isinstance(decoded, dict):
        choices = decoded.get("choices", [])
        if choices:
            delta = choices[0].get("delta", {})
            content = delta.get("content")
            print(f"  Content: {content!r}")

