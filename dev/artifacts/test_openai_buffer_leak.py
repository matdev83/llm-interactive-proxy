"""
Memory leak test for openai.py stream_completion buffer.

This script reproduces a potential memory leak where the SSE buffer
in stream_completion() can grow unbounded when malformed SSE messages
are received without proper separators.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))



class MalformedSSEMock:
    """Mock httpx response that sends malformed SSE data without separators."""

    def __init__(self, chunk_count: int = 50000):
        self.chunk_count = chunk_count
        self.position = 0
        self.closed = False

    async def aiter_bytes(self):
        """Yield chunks that don't contain SSE separators."""
        # Send chunks that don't contain "\n\n" or "\r\n\r\n"
        # This will cause buffer to grow indefinitely
        for i in range(self.chunk_count):
            if self.closed:
                break
            # Each chunk is a partial SSE message without separator
            chunk = b"data: " + str(i).encode() + b" partial-chunk-content" + b" "
            yield chunk
            # No delay to speed up test

    async def aclose(self):
        """Close the mock response."""
        self.closed = True


class TestOpenAIConnector:
    """Minimal OpenAIConnector to test stream_completion method."""

    def __init__(self):
        self.api_base_url = "https://api.openai.com/v1"
        self.api_key = "test-key"

    async def stream_completion(self, request):
        """
        Simplified version of OpenAIConnector.stream_completion that exhibits
        buffer growth issue.
        """
        response = MalformedSSEMock(chunk_count=50000)
        buffer = ""
        separator = "\n\n"
        alt_separator = "\r\n\r\n"
        chunk_count = 0
        buffer_sizes = []

        try:
            async for chunk_bytes in response.aiter_bytes():
                chunk_text = (
                    chunk_bytes.decode("utf-8", errors="replace")
                    if isinstance(chunk_bytes, (bytes, bytearray))
                    else str(chunk_bytes)
                )
                buffer += chunk_text
                chunk_count += 1
                buffer_sizes.append(len(buffer))

                # Try to split on separators
                while True:
                    if alt_separator in buffer:
                        event, buffer = buffer.split(alt_separator, 1)
                        separator_used = alt_separator
                    elif separator in buffer:
                        event, buffer = buffer.split(separator, 1)
                        separator_used = separator
                    else:
                        break

                    if event:
                        pass  # Process event

                # Collect samples at specific intervals
                if chunk_count in [1, 100, 1000, 10000, 50000]:
                    pass

        finally:
            await response.aclose()

        return buffer_sizes


async def main():
    """Run the memory leak test."""
    print("Testing for unbounded buffer growth in stream_completion...")
    print("Sending 50000 malformed SSE chunks without separators...")
    print("(This simulates malicious input without SSE separators)")

    connector = TestOpenAIConnector()
    buffer_sizes = await connector.stream_completion(None)

    print("\nBuffer size progression:")
    print(f"  After 1 chunk:     {buffer_sizes[0]} bytes")
    print(f"  After 100 chunks:   {buffer_sizes[99]} bytes")
    print(f"  After 1000 chunks:  {buffer_sizes[999]} bytes")
    print(f"  After 10000 chunks: {buffer_sizes[9999]} bytes")
    print(f"  After 50000 chunks: {buffer_sizes[-1]} bytes")

    print(f"\nTotal buffer size: {buffer_sizes[-1]} bytes ({buffer_sizes[-1] / 1024 / 1024:.2f} MB)")
    print(f"Average buffer size per chunk: {buffer_sizes[-1] / 50000:.2f} bytes")

    # Check if buffer is growing unbounded
    if buffer_sizes[-1] > 16 * 1024:  # 16KB threshold
        print("\n[!] POTENTIAL MEMORY LEAK DETECTED!")
        print(f"   Buffer grew to {buffer_sizes[-1] / 1024 / 1024:.2f} MB without any truncation.")
        print("   This could lead to unbounded memory growth with malicious input.")
        print("\n   The issue is in src/connectors/openai.py stream_completion() method:")
        print("   - Lines 1275-1303: SSE buffer lacks size limit")
        print("   - The _handle_streaming_response method HAS protection (line 826, MAX_SSE_BUFFER_SIZE)")
        print("   - But stream_completion() does NOT have this protection")
        return 1
    else:
        print("\n[OK] Buffer growth appears bounded")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
