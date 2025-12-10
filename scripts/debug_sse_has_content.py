"""Debug script to verify the has_content check in SSE assembler."""

import sys

sys.path.insert(0, ".")

from src.core.ports.streaming_contracts import StreamingContent

# Simulate the newline chunk
decoded_payload = {
    "choices": [
        {"delta": {"role": "assistant", "content": "\n"}, "finish_reason": None}
    ],
    "id": "gen-123",
    "model": "test",
    "created": 12345,
}

streaming_content = StreamingContent(
    content=decoded_payload,
    metadata={},
    is_done=False,
)

chunk_bytes = streaming_content.to_bytes()
print(f"chunk_bytes: {chunk_bytes!r}")
print(f"chunk_bytes.strip(): {chunk_bytes.strip()!r}")
print(f"bool(chunk_bytes): {bool(chunk_bytes)}")
print(f"bool(chunk_bytes.strip()): {bool(chunk_bytes.strip())}")
print(
    f"chunk_bytes.strip() != b'data: [DONE]': {chunk_bytes.strip() != b'data: [DONE]'}"
)

has_content = bool(
    chunk_bytes and chunk_bytes.strip() and chunk_bytes.strip() != b"data: [DONE]"
)
print(f"has_content: {has_content}")

# Now test with dash chunk
decoded_payload_dash = {
    "choices": [
        {"delta": {"role": "assistant", "content": "-"}, "finish_reason": None}
    ],
    "id": "gen-123",
    "model": "test",
    "created": 12345,
}

streaming_content_dash = StreamingContent(
    content=decoded_payload_dash,
    metadata={},
    is_done=False,
)

chunk_bytes_dash = streaming_content_dash.to_bytes()
print("\n=== Dash chunk ===")
print(f"chunk_bytes: {chunk_bytes_dash!r}")
has_content_dash = bool(
    chunk_bytes_dash
    and chunk_bytes_dash.strip()
    and chunk_bytes_dash.strip() != b"data: [DONE]"
)
print(f"has_content: {has_content_dash}")
