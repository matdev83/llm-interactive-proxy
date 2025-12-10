"""Debug script to trace the full streaming pipeline from backend to client."""

import sys
sys.path.insert(0, ".")

import asyncio
import json
from typing import AsyncIterator, Any

from src.core.domain.chat import (
    CanonicalStreamChunk,
    StreamingChatCompletionChoice,
    StreamingChatCompletionChoiceDelta,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import StreamingContent


# Simulate _stream_as_sse_bytes
def _format_as_sse(content: Any) -> bytes:
    if hasattr(content, "model_dump") and callable(content.model_dump):
        return f"data: {json.dumps(content.model_dump())}\n\n".encode()
    if isinstance(content, dict):
        return f"data: {json.dumps(content)}\n\n".encode()
    return f"data: {content}\n\n".encode()


async def simulate_stream_as_sse_bytes(chunks: list) -> AsyncIterator[bytes]:
    """Simulate what _stream_as_sse_bytes does."""
    for chunk in chunks:
        yield _format_as_sse(chunk)


async def simulate_to_processed_with_capture(
    stream: AsyncIterator[bytes], session_id: str
) -> AsyncIterator[ProcessedResponse]:
    """Simulate _to_processed_with_capture."""
    async for b in stream:
        yield ProcessedResponse(
            content=b,
            metadata={"session_id": session_id, "stream_id": session_id},
        )


def _decode_sse_payload(payload: Any) -> tuple[Any, dict[str, Any], bool]:
    """Decode SSE payload - copy from response_adapters.py"""
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


async def simulate_convert_to_streaming_content(
    source: AsyncIterator[ProcessedResponse],
) -> AsyncIterator[StreamingContent]:
    """Simulate _convert_to_streaming_content - simplified version."""
    chunk_count = 0
    async for chunk in source:
        chunk_count += 1
        print(f"[_convert_to_streaming_content] Chunk #{chunk_count}")
        
        payload = chunk.content
        metadata = chunk.metadata or {}
        
        decoded_payload, sse_metadata, forced_done = _decode_sse_payload(payload)
        print(f"  decoded_payload type: {type(decoded_payload)}")
        
        if isinstance(decoded_payload, dict):
            choices = decoded_payload.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                print(f"  delta.content: {content!r}")
        
        # Simplified: just use decoded_payload as enriched
        enriched = decoded_payload
        
        streaming_content = StreamingContent(
            content=enriched,
            metadata=metadata,
            is_done=False,
        )
        
        print(f"  is_empty: {streaming_content.is_empty}")
        print(f"  content truthy: {bool(streaming_content.content)}")
        
        yield streaming_content


async def simulate_assemble_stream(
    stream: AsyncIterator[StreamingContent],
) -> AsyncIterator[bytes]:
    """Simulate assemble_stream - simplified."""
    async for chunk in stream:
        print(f"[assemble_stream] Processing chunk")
        print(f"  is_empty: {chunk.is_empty}")
        print(f"  is_done: {chunk.is_done}")
        print(f"  content: {bool(chunk.content)}")
        
        # The skip condition
        if chunk.is_empty and not chunk.is_done and not chunk.content:
            print(f"  SKIPPING - empty chunk")
            continue
        
        chunk_bytes = chunk.to_bytes()
        
        has_content = bool(
            chunk_bytes
            and chunk_bytes.strip()
            and chunk_bytes.strip() != b"data: [DONE]"
        )
        
        print(f"  has_content: {has_content}")
        
        if has_content:
            print(f"  YIELDING: {chunk_bytes[:100]}...")
            yield chunk_bytes
        else:
            print(f"  NOT YIELDING - no content")


async def main():
    # Create two chunks: newline and dash
    delta_newline = StreamingChatCompletionChoiceDelta(role="assistant", content="\n")
    choice_newline = StreamingChatCompletionChoice(index=0, delta=delta_newline, finish_reason=None)
    chunk_newline = CanonicalStreamChunk(
        id="gen-123",
        object="chat.completion.chunk",
        created=12345,
        model="test",
        choices=[choice_newline],
    )

    delta_dash = StreamingChatCompletionChoiceDelta(role="assistant", content="-")
    choice_dash = StreamingChatCompletionChoice(index=0, delta=delta_dash, finish_reason=None)
    chunk_dash = CanonicalStreamChunk(
        id="gen-123",
        object="chat.completion.chunk",
        created=12345,
        model="test",
        choices=[choice_dash],
    )

    chunks = [chunk_newline, chunk_dash]
    
    print("=" * 60)
    print("Simulating full pipeline")
    print("=" * 60)
    
    # Run through the pipeline
    sse_bytes_stream = simulate_stream_as_sse_bytes(chunks)
    processed_stream = simulate_to_processed_with_capture(sse_bytes_stream, "test-session")
    streaming_content_stream = simulate_convert_to_streaming_content(processed_stream)
    output_stream = simulate_assemble_stream(streaming_content_stream)
    
    print("\n=== Output bytes (P->C) ===")
    outputs = []
    async for output in output_stream:
        outputs.append(output)
        print(f"Output: {output[:100]}...")
    
    print(f"\n=== Summary ===")
    print(f"Input chunks: {len(chunks)}")
    print(f"Output chunks: {len(outputs)}")
    
    if len(outputs) != len(chunks):
        print("ERROR: Chunk count mismatch!")


if __name__ == "__main__":
    asyncio.run(main())

