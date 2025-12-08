"""
Test script to simulate rapid consecutive chunks arriving together.

This script tests what happens when multiple SSE events arrive in a single 
HTTP chunk and are processed in rapid succession.
"""

import asyncio
import sys
from typing import AsyncIterator, Any

sys.path.insert(0, ".")

from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_contracts import StreamingContent
from src.core.transport.fastapi.response_adapters import to_fastapi_streaming_response
from src.core.domain.responses import StreamingResponseEnvelope


async def simulate_rapid_sse_bytes() -> AsyncIterator[bytes]:
    """Simulate SSE bytes arriving rapidly (same HTTP chunk)."""
    # Two events that would arrive together
    sse1 = b'data: {"choices": [{"delta": {"role": "assistant", "content": "\\n"}, "finish_reason": null}], "id": "gen-123", "model": "test", "created": 12345}\n\n'
    sse2 = b'data: {"choices": [{"delta": {"role": "assistant", "content": "-"}, "finish_reason": null}], "id": "gen-123", "model": "test", "created": 12345}\n\n'
    
    # Yield without any await in between - simulating same event loop tick
    yield sse1
    yield sse2
    yield b'data: [DONE]\n\n'


async def simulate_processed_response_stream() -> AsyncIterator[ProcessedResponse]:
    """Wrap SSE bytes in ProcessedResponse like _to_processed_with_capture does."""
    async for sse_bytes in simulate_rapid_sse_bytes():
        yield ProcessedResponse(
            content=sse_bytes,
            metadata={"session_id": "test-session", "stream_id": "test-session"},
        )


async def count_output_chunks():
    """Count how many chunks come out of the streaming response."""
    # Create envelope
    envelope = StreamingResponseEnvelope(
        content=simulate_processed_response_stream(),
        media_type="text/event-stream",
        headers={},
    )
    
    # Convert to FastAPI streaming response
    response = to_fastapi_streaming_response(envelope, wire_capture=None, context=None)
    
    # Count output chunks
    output_count = 0
    async for chunk in response.body_iterator:
        output_count += 1
        text = chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
        # Parse to see content
        for line in text.strip().split("\n\n"):
            if line.startswith("data:"):
                print(f"Output #{output_count}: {line[:80]}...")
    
    return output_count


async def main():
    print("=" * 60)
    print("Testing rapid consecutive chunks")
    print("=" * 60)
    print()
    
    print("Input: 2 content chunks + 1 [DONE]")
    print()
    
    output_count = await count_output_chunks()
    
    print()
    print(f"Output chunks: {output_count}")
    
    # We expect 3 outputs: newline, dash, [DONE]
    if output_count == 3:
        print("SUCCESS: All chunks preserved!")
    else:
        print(f"FAILURE: Expected 3 chunks, got {output_count}")


if __name__ == "__main__":
    asyncio.run(main())

