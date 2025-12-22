#!/usr/bin/env python3
"""
DoS vulnerability reproduction script for OpenAI connector buffer overflow.

This script demonstrates how a malicious streaming response can cause 
unbounded memory growth in the OpenAI connector's buffer processing.
"""

import asyncio
import logging

# Set up logging to see the issue
logging.basicConfig(level=logging.INFO)

async def simulate_malicious_stream():
    """
    Simulate a streaming response that never contains SSE separators,
    causing the buffer to grow indefinitely.
    """
    # Simulate chunks that contain data but no SSE separators
    malicious_chunks = [
        b"data: {\"chunk\": \"part1\"", 
        b" and more data without separators\"",
        b"just keep adding data",
        b"no \\n\\n separators here",
        b"buffer keeps growing...",
    ] * 100  # Repeat to show the issue
    
    # Create async iterator that yields malicious chunks
    async def mock_aiter_bytes():
        for chunk in malicious_chunks:
            yield chunk
            await asyncio.sleep(0.001)  # Small delay to simulate real streaming
    
    return mock_aiter_bytes()

async def demonstrate_buffer_overflow():
    """
    Demonstrate the buffer overflow vulnerability in the OpenAI connector.
    This reproduces the exact vulnerable code from src/connectors/openai.py
    """
    print("Starting DoS vulnerability demonstration...")
    print("This shows how unbounded buffer growth can occur in streaming processing.")
    print("Reproducing the vulnerable code from src/connectors/openai.py:stream_sse_generator()")
    
    # Get malicious response generator
    malicious_response_generator = await simulate_malicious_stream()
    
    print("Simulating processing of malicious stream...")
    print("(This mimics the exact vulnerable code in OpenAI connector)")
    
    # Track buffer size growth
    buffer_sizes = []
    
    async def vulnerable_sse_processing(response_generator):
        """
        This is the VULNERABLE code copied from src/connectors/openai.py
        Lines ~460-490 in the stream_sse_generator method
        """
        buffer = ""
        separator = "\n\n"
        alt_separator = "\r\n\r\n"
        
        try:
            async for chunk_bytes in response_generator:  # Fixed: removed ()
                chunk_text = (
                    chunk_bytes.decode("utf-8", errors="replace")
                    if isinstance(chunk_bytes, bytes | bytearray)
                    else str(chunk_bytes)
                )
                
                # VULNERABILITY: Buffer grows without any size limits
                buffer += chunk_text
                buffer_sizes.append(len(buffer))
                
                # Show buffer growth
                if len(buffer_sizes) % 20 == 0:
                    print(f"Buffer size: {len(buffer)} characters (chunks processed: {len(buffer_sizes)})")
                
                # Try to process SSE events (this will fail for malicious input)
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
                        yield event + separator_used
                        
                # Safety check to prevent actual memory exhaustion in demo
                if len(buffer) > 50000:  # 50KB limit for demo
                    print(f"\nSTOPPING: Buffer reached {len(buffer)} characters to prevent system exhaustion")
                    print(f"Processed {len(buffer_sizes)} chunks before stopping")
                    return
                    
        except Exception as e:
            print(f"Exception occurred: {e}")
            print(f"Final buffer size: {len(buffer)} characters")
    
    # Run the vulnerable processing
    try:
        events_processed = 0
        async for event in vulnerable_sse_processing(malicious_response_generator):
            events_processed += 1
    except Exception as e:
        print(f"Processing failed with: {e}")
    
    print(f"\nATTACK SCENARIO:")
    print(f"1. Attacker initiates streaming request to OpenAI-compatible endpoint")
    print(f"2. Attacker-controlled upstream sends malicious response without SSE separators")
    print(f"3. Buffer grows unbounded as shown above")
    print(f"4. Server memory exhausted => Denial of Service")
    
    print(f"\n=== VULNERABILITY CONFIRMED ===")
    print(f"Maximum buffer size reached: {max(buffer_sizes) if buffer_sizes else 0}")
    print(f"Total chunks processed: {len(buffer_sizes)}")
    print(f"Events processed: {events_processed}")
    
    print(f"\nATTACK SCENARIO:")
    print(f"1. Attacker initiates streaming request to OpenAI-compatible endpoint")
    print(f"2. Attacker-controlled upstream sends malicious response without SSE separators")
    print(f"3. Buffer grows unbounded as shown above")
    print(f"4. Server memory exhausted → Denial of Service")
    
    print(f"\nFIX REQUIRED:")
    print(f"Add maximum buffer size limits to prevent unbounded growth")

if __name__ == "__main__":
    asyncio.run(demonstrate_buffer_overflow())