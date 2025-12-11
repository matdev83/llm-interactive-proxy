"""Debug script to verify StreamingContent behavior with dict containing newline."""

import sys

sys.path.insert(0, ".")

from src.core.ports.streaming_contracts import StreamingContent

# Simulate what happens when _decode_sse_payload returns a decoded dict
decoded_payload = {
    "choices": [
        {"delta": {"role": "assistant", "content": "\n"}, "finish_reason": None}
    ],
    "id": "gen-123",
    "model": "test",
    "created": 12345,
}

# After _inject_reasoning_metadata, the enriched payload might be the same
enriched = decoded_payload  # Assume no reasoning to inject

# Now StreamingContent is created with this dict
streaming_content = StreamingContent(
    content=enriched,
    metadata={},
    is_done=False,
)

print(f"content type: {type(streaming_content.content)}")
print(f"is_empty: {streaming_content.is_empty}")
print(f"is_done: {streaming_content.is_done}")
print(f"content truthy: {bool(streaming_content.content)}")

# The SSE assembler check is: if chunk.is_empty and not chunk.is_done and not chunk.content
condition = (
    streaming_content.is_empty
    and not streaming_content.is_done
    and not streaming_content.content
)
print(f"Skip condition (is_empty and not is_done and not content): {condition}")

# Let's also check what to_bytes produces
bytes_output = streaming_content.to_bytes()
print(f"to_bytes output: {bytes_output!r}")

# Now test with a dash (non-whitespace content)
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

print("\n=== Dash chunk ===")
print(f"is_empty: {streaming_content_dash.is_empty}")
print(
    f"Skip condition: {streaming_content_dash.is_empty and not streaming_content_dash.is_done and not streaming_content_dash.content}"
)
print(f"to_bytes: {streaming_content_dash.to_bytes()!r}")
