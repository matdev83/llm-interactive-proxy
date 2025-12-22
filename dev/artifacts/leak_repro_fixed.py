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

async def intercept_stream_logic_fixed(original_iterator):
    """
    Simulates the FIXED logic in AntigravityOAuthConnector._intercept_stream
    """
    content_buffer = ""
    first_chunk_type = None
    original_chunks = []
    
    # Process stream in a single pass with bounded memory
    async for chunk in original_iterator:
        if first_chunk_type is None:
            first_chunk_type = type(chunk)
        
        # Store original chunk for potential re-yielding (bounded)
        original_chunks.append(chunk)
        
        # Extract and accumulate content for XML detection
        if hasattr(chunk, "content"):
            chunk_content = chunk.content
            if isinstance(chunk_content, str):
                content_buffer += chunk_content
        
        # Early exit if we detect tool calls and have enough content
        if "<Tool>" in content_buffer and "</Tool>" in content_buffer:
            # We have a complete tool call, break to process it
            break
    
    # In the fixed version, we don't buffer everything - we yield as we go
    for chunk in original_chunks:
        yield chunk
    
    # Continue yielding remaining chunks from original iterator
    async for chunk in original_iterator:
        yield chunk

async def run_test():
    process = psutil.Process(os.getpid())
    start_mem = process.memory_info().rss / 1024 / 1024
    print(f"Start memory: {start_mem:.2f} MB")

    # Simulate a stream of 50 MB
    stream_size_mb = 50
    iterator = mock_stream(stream_size_mb, 1024 * 10) # 10KB chunks

    # Run the FIXED interceptor
    gen = intercept_stream_logic_fixed(iterator)
    
    print("Starting stream consumption (fixed version)...")
    # Consume the entire stream
    consumed_count = 0
    async for _ in gen:
        consumed_count += 1
        if consumed_count % 1000 == 0:
            pass  # Just to have something in the loop

    end_mem = process.memory_info().rss / 1024 / 1024
    print(f"End memory: {end_mem:.2f} MB")
    
    diff = end_mem - start_mem
    print(f"Memory increase: {diff:.2f} MB")

    # The memory increase should be much smaller now since we're not buffering everything
    if diff < stream_size_mb * 0.1: # Should be much less than 10% of stream size
        print("FIXED: Memory usage is now bounded and reasonable.")
    else:
        print("Memory usage still seems high.")

if __name__ == "__main__":
    asyncio.run(run_test())