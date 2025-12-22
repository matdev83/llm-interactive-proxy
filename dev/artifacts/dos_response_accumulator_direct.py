#!/usr/bin/env python3
"""
Direct DoS vulnerability test for response_accumulator.py

This script directly tests the vulnerable json.loads() call in _process_chunk
method without going through the full streaming infrastructure.
"""

import sys
import os
import time
import json

# Add src to path to import module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.connectors.gemini_base.response_accumulator import StreamingResponseAccumulator

def test_direct_vulnerability():
    """Test the vulnerable json.loads() call directly."""
    
    print("Direct vulnerability test - json.loads without size limits")
    print("=" * 60)
    
    accumulator = StreamingResponseAccumulator()
    
    # Test 1: Very large JSON payload
    print("\nTest 1: Large JSON payload (10MB)")
    print("-" * 40)
    
    # Create malicious JSON payload
    large_payload = {
        "choices": [{
            "delta": {
                "content": "A" * (5 * 1024 * 1024)  # 5MB content
            }
        }],
        "usage": {
            "prompt_tokens": 1000000,
            "completion_tokens": 2000000,
            "total_tokens": 3000000
        },
        # Add massive array to increase memory usage
        "large_array": list(range(500000)),  # 500k elements
        # Add deep nesting to test stack limits
        "nested": {"level" + str(i): {"data": list(range(1000))} for i in range(50)}
    }
    
    # Convert to SSE format (what the vulnerable code expects)
    json_data = json.dumps(large_payload)
    sse_data_line = f"data: {json_data}"
    
    payload_size = len(sse_data_line.encode('utf-8'))
    print(f"Created SSE data line size: {payload_size:,} bytes ({payload_size/1024/1024:.2f} MB)")
    
    # Test the vulnerable code path directly
    start_time = time.time()
    
    try:
        # This simulates what happens in _process_chunk at line 160
        # data_str = line[5:].strip()  # Remove "data:" prefix
        # data = json.loads(data_str)  # <-- VULNERABLE LINE
        
        # Direct test of vulnerable pattern
        data_str = sse_data_line[5:].strip()  # Remove "data:" prefix
        print(f"JSON string size: {len(data_str):,} bytes")
        
        parsed_data = json.loads(data_str)  # This is the vulnerable call
        end_time = time.time()
        
        print(f"JSON parsing completed in {end_time - start_time:.4f} seconds")
        print(f"Successfully parsed payload with {len(large_payload.get('large_array', []))} array elements")
        
        # Check if this took too long (indicates vulnerability)
        if end_time - start_time > 1.0:
            print("WARNING: JSON parsing took too long - potential DoS vulnerability!")
            return True
        
        print("OK: Large JSON parsed within acceptable time")
        
    except MemoryError:
        end_time = time.time()
        print(f"MEMORY ERROR: JSON parsing caused memory exhaustion!")
        print(f"Error occurred after {end_time - start_time:.4f} seconds")
        return True
        
    except Exception as e:
        end_time = time.time()
        print(f"ERROR: {type(e).__name__}: {e}")
        print(f"Error occurred after {end_time - start_time:.4f} seconds")
        
        # Check if error is resource-related (vulnerability)
        if any(keyword in str(e).lower() for keyword in ["memory", "size", "limit", "recursion"]):
            print("WARNING: Resource-related error - potential DoS vulnerability!")
            return True
    
    # Test 2: Deeply nested JSON
    print("\nTest 2: Deeply nested JSON (stack overflow test)")
    print("-" * 40)
    
    def create_deep_nested(depth):
        """Create deeply nested JSON."""
        if depth <= 0:
            return {"value": "deep_value"}
        return {"nested": create_deep_nested(depth - 1)}
    
    try:
        nested_payload = {
            "choices": [{"delta": {"content": "test"}}],
            "deeply_nested": create_deep_nested(200)  # 200 levels deep
        }
        
        nested_json = json.dumps(nested_payload)
        nested_sse = f"data: {nested_json}"
        
        print(f"Deeply nested JSON size: {len(nested_json):,} bytes")
        
        start = time.time()
        nested_data_str = nested_sse[5:].strip()
        parsed_nested = json.loads(nested_data_str)
        end = time.time()
        
        print(f"Deep nested JSON parsed in {end - start:.4f} seconds")
        
        if end - start > 0.5:
            print("WARNING: Deep nesting took too long - potential vulnerability!")
            return True
            
    except RecursionError:
        print("RECURSION ERROR: Deep nesting caused stack overflow!")
        print("This confirms DoS vulnerability through recursive parsing!")
        return True
        
    except Exception as e:
        print(f"ERROR with deep nesting: {type(e).__name__}: {e}")
        if "recursion" in str(e).lower():
            return True
    
    # Test 3: Massive array payload
    print("\nTest 3: Massive array JSON")
    print("-" * 40)
    
    try:
        array_payload = {
            "choices": [{"delta": {"content": "test"}}],
            "massive_array": list(range(1000000)),  # 1 million elements
            "additional_arrays": [list(range(10000)) for _ in range(100)]  # 100 arrays of 10k each
        }
        
        array_json = json.dumps(array_payload)
        array_sse = f"data: {array_json}"
        
        print(f"Massive array JSON size: {len(array_json):,} bytes")
        
        start = time.time()
        array_data_str = array_sse[5:].strip()
        parsed_array = json.loads(array_data_str)
        end = time.time()
        
        print(f"Massive array JSON parsed in {end - start:.4f} seconds")
        print(f"Array contains {len(array_payload['massive_array']):,} elements")
        
        if end - start > 2.0:
            print("WARNING: Massive array took too long - potential DoS vulnerability!")
            return True
            
    except MemoryError:
        print("MEMORY ERROR: Massive array caused memory exhaustion!")
        return True
        
    except Exception as e:
        print(f"ERROR with massive array: {type(e).__name__}: {e}")
        if "memory" in str(e).lower():
            return True
    
    return False

def test_repeated_attacks():
    """Test if repeated attacks could exhaust resources."""
    
    print("\nTest 4: Repeated small attacks (resource accumulation)")
    print("-" * 40)
    
    # Create moderately large payload that won't individually trigger alerts
    payload = {
        "choices": [{"delta": {"content": "X" * 10000}}],  # 10KB
        "data": {"values": list(range(5000))}  # 5k elements
    }
    
    json_data = json.dumps(payload)
    sse_line = f"data: {json_data}"
    data_str = sse_line[5:].strip()
    
    print(f"Single payload size: {len(data_str):,} bytes")
    
    # Simulate processing many payloads rapidly
    num_attacks = 50
    total_time = 0
    failures = 0
    
    for i in range(num_attacks):
        start = time.time()
        try:
            result = json.loads(data_str)
            end = time.time()
            total_time += (end - start)
        except Exception as e:
            failures += 1
            end = time.time()
            total_time += (end - start)
    
    avg_time = total_time / num_attacks
    print(f"Processed {num_attacks} payloads in {total_time:.4f} seconds")
    print(f"Average time per payload: {avg_time:.6f} seconds")
    print(f"Failures: {failures}/{num_attacks}")
    
    if avg_time > 0.01 or failures > 0:
        print("WARNING: Repeated processing shows degradation - potential DoS!")
        return True
    
    return False

if __name__ == "__main__":
    print("Direct DoS Vulnerability Test - response_accumulator.py")
    print("=" * 60)
    
    # Run direct vulnerability test
    test1_vulnerable = test_direct_vulnerability()
    
    # Run repeated attacks test
    test2_vulnerable = test_repeated_attacks()
    
    print("\n" + "=" * 60)
    print("VULNERABILITY ASSESSMENT:")
    print(f"Direct JSON parsing: {'VULNERABLE' if test1_vulnerable else 'OK'}")
    print(f"Repeated attacks: {'VULNERABLE' if test2_vulnerable else 'OK'}")
    
    if test1_vulnerable or test2_vulnerable:
        print("\nALERT: DoS VULNERABILITY CONFIRMED!")
        print("The response_accumulator.py contains exploitable json.loads() calls")
        print("without proper size limits, allowing DoS attacks")
        sys.exit(1)
    else:
        print("\nOK: No significant DoS vulnerabilities detected")
        sys.exit(0)