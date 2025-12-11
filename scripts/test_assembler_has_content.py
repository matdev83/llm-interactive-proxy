"""Test the has_content logic in SSEAssembler."""

import sys

sys.path.insert(0, ".")

# Simulate what StreamingContent.to_bytes() produces
newline_bytes = b'data: {"id": "gen-123", "object": "chat.completion.chunk", "created": 12345, "model": "test", "choices": [{"index": 0, "finish_reason": null, "delta": {"role": "assistant", "content": "\\n"}}]}\n\n'

dash_bytes = b'data: {"id": "gen-123", "object": "chat.completion.chunk", "created": 12345, "model": "test", "choices": [{"index": 0, "finish_reason": null, "delta": {"role": "assistant", "content": "-"}}]}\n\n'


def check_has_content(chunk_bytes: bytes, label: str):
    has_content = bool(
        chunk_bytes and chunk_bytes.strip() and chunk_bytes.strip() != b"data: [DONE]"
    )

    print(f"{label}:")
    print(f"  chunk_bytes truthy: {bool(chunk_bytes)}")
    print(f"  chunk_bytes.strip() truthy: {bool(chunk_bytes.strip())}")
    print(
        f"  chunk_bytes.strip() != b'data: [DONE]': {chunk_bytes.strip() != b'data: [DONE]'}"
    )
    print(f"  has_content: {has_content}")
    print()


check_has_content(newline_bytes, "Newline chunk")
check_has_content(dash_bytes, "Dash chunk")
