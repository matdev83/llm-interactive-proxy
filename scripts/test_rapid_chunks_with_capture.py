"""
Test script to simulate rapid consecutive chunks with wire capture enabled.
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


# Mock wire capture that tracks what it captures
class MockWireCapture:
    def __init__(self):
        self.inbound_chunks = []
        self.outbound_chunks = []
        
    def enabled(self) -> bool:
        return True
    
    def wrap_inbound_stream(self, **kwargs) -> AsyncIterator[bytes]:
        stream = kwargs.get("stream")
        
        async def _capture():
            async for chunk in stream:
                self.inbound_chunks.append(chunk)
                yield chunk
        
        return _capture()
    
    def wrap_outbound_stream(self, **kwargs) -> AsyncIterator[bytes]:
        stream = kwargs.get("stream")
        
        async def _capture():
            async for chunk in stream:
                self.outbound_chunks.append(chunk)
                yield chunk
        
        return _capture()


async def simulate_rapid_sse_bytes() -> AsyncIterator[bytes]:
    """Simulate SSE bytes arriving rapidly (same HTTP chunk)."""
    sse1 = b'data: {"choices": [{"delta": {"role": "assistant", "content": "\\n"}, "finish_reason": null}], "id": "gen-123", "model": "test", "created": 12345}\n\n'
    sse2 = b'data: {"choices": [{"delta": {"role": "assistant", "content": "-"}, "finish_reason": null}], "id": "gen-123", "model": "test", "created": 12345}\n\n'
    
    yield sse1
    yield sse2
    yield b'data: [DONE]\n\n'


async def simulate_processed_response_stream() -> AsyncIterator[ProcessedResponse]:
    """Wrap SSE bytes in ProcessedResponse."""
    async for sse_bytes in simulate_rapid_sse_bytes():
        yield ProcessedResponse(
            content=sse_bytes,
            metadata={"session_id": "test-session", "stream_id": "test-session"},
        )


async def test_with_wire_capture():
    """Test streaming with mock wire capture."""
    wire_capture = MockWireCapture()
    
    # Create envelope
    envelope = StreamingResponseEnvelope(
        content=simulate_processed_response_stream(),
        media_type="text/event-stream",
        headers={},
    )
    
    # Convert to FastAPI streaming response WITH wire capture
    response = to_fastapi_streaming_response(
        envelope, 
        wire_capture=wire_capture, 
        context=None
    )
    
    # Consume the stream
    output_count = 0
    async for chunk in response.body_iterator:
        output_count += 1
    
    print("Wire Capture Results:")
    print(f"  Outbound chunks captured: {len(wire_capture.outbound_chunks)}")
    
    print("\nOutbound chunks content:")
    for i, chunk in enumerate(wire_capture.outbound_chunks):
        text = chunk.decode("utf-8")
        for line in text.strip().split("\n\n"):
            if line.startswith("data:"):
                # Check content
                if '"content":' in line:
                    # Extract content value
                    import json
                    try:
                        parsed = json.loads(line[5:].strip())
                        choices = parsed.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "N/A")
                            print(f"  Chunk {i+1}: content={content!r}")
                    except:
                        print(f"  Chunk {i+1}: {line[:50]}...")
                elif "[DONE]" in line:
                    print(f"  Chunk {i+1}: [DONE]")
    
    return wire_capture


async def main():
    print("=" * 60)
    print("Testing with mock wire capture")
    print("=" * 60)
    print()
    
    wire_capture = await test_with_wire_capture()
    
    # Verify
    newline_found = False
    dash_found = False
    
    for chunk in wire_capture.outbound_chunks:
        text = chunk.decode("utf-8")
        if '"content": "\\n"' in text or '"content":"\\n"' in text:
            newline_found = True
        if '"content": "-"' in text or '"content":"-"' in text:
            dash_found = True
    
    print()
    if newline_found and dash_found:
        print("SUCCESS: Both newline and dash chunks captured!")
    else:
        print(f"FAILURE: newline_found={newline_found}, dash_found={dash_found}")


if __name__ == "__main__":
    asyncio.run(main())

