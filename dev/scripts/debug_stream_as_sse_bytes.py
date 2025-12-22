"""Debug script to trace what _stream_as_sse_bytes produces."""

import sys

sys.path.insert(0, ".")

from src.core.domain.chat import (
    CanonicalStreamChunk,
    StreamingChatCompletionChoice,
    StreamingChatCompletionChoiceDelta,
)

# Create a CanonicalStreamChunk with newline content
delta = StreamingChatCompletionChoiceDelta(role="assistant", content="\n")
choice = StreamingChatCompletionChoice(index=0, delta=delta, finish_reason=None)
chunk_newline = CanonicalStreamChunk(
    id="gen-123",
    object="chat.completion.chunk",
    created=12345,
    model="test",
    choices=[choice],
)

# Create a CanonicalStreamChunk with dash content
delta_dash = StreamingChatCompletionChoiceDelta(role="assistant", content="-")
choice_dash = StreamingChatCompletionChoice(
    index=0, delta=delta_dash, finish_reason=None
)
chunk_dash = CanonicalStreamChunk(
    id="gen-123",
    object="chat.completion.chunk",
    created=12345,
    model="test",
    choices=[choice_dash],
)

# Simulate the _format_as_sse function from backend_service.py
import json


def _format_as_sse(content):
    """Normalize arbitrary content to SSE-framed bytes."""
    if isinstance(content, bytes | bytearray):
        stripped_bytes = bytes(content).strip()
        if stripped_bytes.startswith(b"data:"):
            return bytes(content)
        if stripped_bytes in (b"[DONE]", b'["DONE"]'):
            return b"data: [DONE]\n\n"
        text_val = content.decode("utf-8", errors="replace")
        return f"data: {text_val}\n\n".encode()

    if isinstance(content, str):
        stripped_text = content.strip()
        if stripped_text.startswith("data:"):
            return content.encode("utf-8")
        if stripped_text in ("[DONE]", '["DONE"]'):
            return b"data: [DONE]\n\n"
        return f"data: {content}\n\n".encode()

    # Handle Pydantic models (like CanonicalStreamChunk) by converting to dict
    if hasattr(content, "model_dump") and callable(content.model_dump):
        return f"data: {json.dumps(content.model_dump())}\n\n".encode()

    if isinstance(content, dict):
        return f"data: {json.dumps(content)}\n\n".encode()

    # Fallback
    try:
        return f"data: {json.dumps(content)}\n\n".encode()
    except (TypeError, ValueError):
        return f"data: {content}\n\n".encode()


# Test the conversion
bytes_newline = _format_as_sse(chunk_newline)
bytes_dash = _format_as_sse(chunk_dash)

print("=== Newline chunk ===")
print(f"SSE bytes: {bytes_newline!r}")

print("\n=== Dash chunk ===")
print(f"SSE bytes: {bytes_dash!r}")

# Now decode these back using _decode_sse_payload logic


def _decode_sse_payload(payload):
    """Decode SSE-formatted payloads into structured content."""
    text_payload = None
    if isinstance(payload, bytes | bytearray):
        try:
            text_payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return payload, {}, False
    elif isinstance(payload, str):
        text_payload = payload
    else:
        return payload, {}, False

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


print("\n=== Decoding SSE back ===")
decoded_newline, _, _ = _decode_sse_payload(bytes_newline)
decoded_dash, _, _ = _decode_sse_payload(bytes_dash)

print(f"Decoded newline: {decoded_newline}")
print(f"Decoded dash: {decoded_dash}")

# Check the content field
if isinstance(decoded_newline, dict):
    choices = decoded_newline.get("choices", [])
    if choices:
        delta = choices[0].get("delta", {})
        content = delta.get("content")
        print(f"Newline content field: {content!r}")

if isinstance(decoded_dash, dict):
    choices = decoded_dash.get("choices", [])
    if choices:
        delta = choices[0].get("delta", {})
        content = delta.get("content")
        print(f"Dash content field: {content!r}")
