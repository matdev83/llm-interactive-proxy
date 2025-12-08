"""
Reproduction script for whitespace chunk dropping issue.

This script simulates the exact streaming pipeline flow to identify where
whitespace-only chunks are being dropped.
"""

import asyncio
import json
import sys
from typing import Any, AsyncIterator

sys.path.insert(0, ".")

from src.core.domain.chat import (
    CanonicalStreamChunk,
    StreamingChatCompletionChoice,
    StreamingChatCompletionChoiceDelta,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_contracts import StreamingContent


def create_openai_chunk(content: str, chunk_id: str = "gen-123") -> CanonicalStreamChunk:
    """Create an OpenAI-style streaming chunk."""
    delta = StreamingChatCompletionChoiceDelta(role="assistant", content=content)
    choice = StreamingChatCompletionChoice(index=0, delta=delta, finish_reason=None)
    return CanonicalStreamChunk(
        id=chunk_id,
        object="chat.completion.chunk",
        created=12345,
        model="test-model",
        choices=[choice],
    )


def format_as_sse(content: Any) -> bytes:
    """Format content as SSE bytes (simulating _stream_as_sse_bytes)."""
    if hasattr(content, "model_dump") and callable(content.model_dump):
        return f"data: {json.dumps(content.model_dump())}\n\n".encode()
    if isinstance(content, dict):
        return f"data: {json.dumps(content)}\n\n".encode()
    return f"data: {content}\n\n".encode()


def decode_sse_payload(payload: bytes) -> tuple[Any, dict, bool]:
    """Decode SSE payload (simulating _decode_sse_payload)."""
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
    if data_body == "[DONE]":
        return "", {"finish_reason": "stop"}, True
    
    try:
        decoded = json.loads(data_body)
    except json.JSONDecodeError:
        return data_body, {}, False
    
    return decoded, {}, False


async def simulate_backend_stream(chunks: list[CanonicalStreamChunk]) -> AsyncIterator[ProcessedResponse]:
    """Simulate what the backend connector yields."""
    for chunk in chunks:
        yield ProcessedResponse(content=chunk)


async def simulate_stream_as_sse_bytes(source: AsyncIterator[ProcessedResponse]) -> AsyncIterator[bytes]:
    """Simulate _stream_as_sse_bytes."""
    async for item in source:
        content = item.content if isinstance(item, ProcessedResponse) else item
        yield format_as_sse(content)
    yield b"data: [DONE]\n\n"


async def simulate_wrap_inbound_stream(stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Simulate wrap_inbound_stream (B->P capture wrapper)."""
    chunk_idx = 0
    async for chunk in stream:
        chunk_idx += 1
        print(f"[B->P] Captured chunk #{chunk_idx}: {chunk[:80]}...")
        yield chunk


async def simulate_to_processed_with_capture(stream: AsyncIterator[bytes]) -> AsyncIterator[ProcessedResponse]:
    """Simulate _to_processed_with_capture."""
    async for chunk in stream:
        yield ProcessedResponse(
            content=chunk,
            metadata={"session_id": "test-session", "stream_id": "test-session"},
        )


async def simulate_convert_to_streaming_content(source: AsyncIterator[ProcessedResponse]) -> AsyncIterator[StreamingContent]:
    """Simulate _convert_to_streaming_content."""
    async for item in source:
        payload = item.content
        metadata = item.metadata or {}
        
        decoded, _, _ = decode_sse_payload(payload)
        
        # Create StreamingContent with decoded payload
        streaming_content = StreamingContent(
            content=decoded,
            metadata=metadata,
            is_done=isinstance(decoded, str) and decoded == "",
        )
        
        yield streaming_content


async def simulate_assemble_stream(stream: AsyncIterator[StreamingContent]) -> AsyncIterator[bytes]:
    """Simulate assemble_stream using actual SSEAssembler."""
    assembler = SSEAssembler()
    async for chunk in assembler.assemble_stream(stream, format="sse"):
        yield chunk


async def simulate_wrap_outbound_stream(stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Simulate wrap_outbound_stream (P->C capture wrapper)."""
    chunk_idx = 0
    async for chunk in stream:
        chunk_idx += 1
        print(f"[P->C] Captured chunk #{chunk_idx}: {chunk[:80]}...")
        yield chunk


async def main():
    # Create test chunks: newline followed by dash (the problematic pattern)
    chunks = [
        create_openai_chunk("\n"),  # Whitespace-only
        create_openai_chunk("-"),   # Non-whitespace
    ]
    
    print("=" * 60)
    print("Testing streaming pipeline with whitespace chunk")
    print("=" * 60)
    print(f"Input chunks: {len(chunks)}")
    for i, chunk in enumerate(chunks):
        content = chunk.choices[0].delta.content
        print(f"  Chunk {i}: content={content!r}")
    print()
    
    # Run through the full pipeline
    backend_stream = simulate_backend_stream(chunks)
    sse_bytes_stream = simulate_stream_as_sse_bytes(backend_stream)
    inbound_captured = simulate_wrap_inbound_stream(sse_bytes_stream)
    processed_stream = simulate_to_processed_with_capture(inbound_captured)
    streaming_content_stream = simulate_convert_to_streaming_content(processed_stream)
    assembled_stream = simulate_assemble_stream(streaming_content_stream)
    outbound_captured = simulate_wrap_outbound_stream(assembled_stream)
    
    # Consume the stream
    print("\n=== Running pipeline ===\n")
    output_chunks = []
    async for chunk in outbound_captured:
        output_chunks.append(chunk)
    
    print(f"\n=== Summary ===")
    print(f"Input chunks: {len(chunks)}")
    print(f"B->P captures expected: {len(chunks) + 1}")  # +1 for [DONE]
    print(f"P->C captures (output): {len(output_chunks)}")
    
    if len(output_chunks) != len(chunks) + 1:  # +1 for [DONE]
        print("\nERROR: Chunk count mismatch!")
    else:
        print("\nSUCCESS: All chunks passed through!")


if __name__ == "__main__":
    asyncio.run(main())

