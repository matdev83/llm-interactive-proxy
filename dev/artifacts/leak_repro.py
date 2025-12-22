import asyncio
import sys
import os
import psutil

# Mock class to simulate the objects used in the connector
class MockChunk:
    def __init__(self, content):
        self.content = content

async def mock_stream(total_size_mb, chunk_size_bytes):
    """Yields chunks of data until total_size_mb is reached."""
    total_bytes = total_size_mb * 1024 * 1024
    yielded_bytes = 0
    chunk_data = "x" * chunk_size_bytes
    
    while yielded_bytes < total_bytes:
        yield MockChunk(chunk_data)
        yielded_bytes += chunk_size_bytes
        # Yield to event loop to allow other tasks to run
        await asyncio.sleep(0)

async def intercept_stream_logic(original_iterator):
    """
    Simulates the logic in AntigravityOAuthConnector._intercept_stream
    """
    buffer = []
    # This loop buffers the ENTIRE stream before proceeding
    async for chunk in original_iterator:
        buffer.append(chunk)
    
    # In the original code, processing happens here
    full_content = ""
    for chunk in buffer:
        full_content += chunk.content
    
    # Then it yields
    for chunk in buffer:
        yield chunk

async def run_test():
    process = psutil.Process(os.getpid())
    start_mem = process.memory_info().rss / 1024 / 1024
    print(f"Start memory: {start_mem:.2f} MB")

    # Simulate a stream of 50 MB
    stream_size_mb = 50
    iterator = mock_stream(stream_size_mb, 1024 * 10) # 10KB chunks

    # Run the interceptor
    # We expect this to consume at least 50MB of RAM because it buffers everything
    gen = intercept_stream_logic(iterator)
    
    print("Starting stream consumption...")
    # We only need to try to get the first chunk to trigger the buffering
    try:
        async for _ in gen:
            break
    except Exception as e:
        print(f"Error: {e}")

    end_mem = process.memory_info().rss / 1024 / 1024
    print(f"End memory: {end_mem:.2f} MB")
    
    diff = end_mem - start_mem
    print(f"Memory increase: {diff:.2f} MB")

    if diff > stream_size_mb * 0.8: # Allow some slack, but it should be close to stream size
        print("CONFIRMED: Memory leak / unbounded buffering detected.")
    else:
        print("Test passed? Memory usage didn't spike as expected (or GC kicked in very hard).")

if __name__ == "__main__":
    asyncio.run(run_test())
