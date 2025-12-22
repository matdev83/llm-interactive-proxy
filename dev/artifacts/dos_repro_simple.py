#!/usr/bin/env python3
"""
DoS vulnerability reproduction script for ContentRewritingMiddleware.
This script demonstrates how malicious JSON payloads can cause excessive CPU/memory usage.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# Add the src directory to the path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def test_json_dos_vectors():
    """Test various DoS vectors in JSON parsing."""
    
    print("Testing DoS vectors for ContentRewritingMiddleware...")
    
    # Vector 1: Massive array payload
    print("\n1. Testing massive array payload...")
    start_time = time.time()
    
    try:
        # Create payload with 1 million items - this will consume significant memory
        massive_array_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "large_array": list(range(1000000)),  # 1 million integers
        }
        
        json_str = json.dumps(massive_array_payload)
        json_bytes = json_str.encode('utf-8')
        
        # Simulate what the vulnerable middleware does
        parsed = json.loads(json_bytes)
        
        array_time = time.time() - start_time
        print(f"   Array size: {len(parsed['large_array'])} elements")
        print(f"   Processing time: {array_time:.2f} seconds")
        print(f"   JSON size: {len(json_bytes) / (1024*1024):.2f} MB")
        
        if array_time > 1.0:
            print("   ⚠️  DELAY: This could be used for DoS!")
        
    except Exception as e:
        print(f"   ERROR: {e}")
    
    # Vector 2: Deeply nested structure (stack overflow)
    print("\n2. Testing deeply nested payload...")
    start_time = time.time()
    
    try:
        # Create payload with 500 levels of nesting
        nested_data = {"value": "root"}
        for i in range(500):
            nested_data = {"nested": nested_data, "level": i}
        
        nested_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "deeply_nested": nested_data,
        }
        
        json_str = json.dumps(nested_payload)
        json_bytes = json_str.encode('utf-8')
        
        # This could cause stack overflow in some JSON parsers
        parsed = json.loads(json_bytes)
        
        nested_time = time.time() - start_time
        print(f"   Nesting depth: 500 levels")
        print(f"   Processing time: {nested_time:.2f} seconds")
        
        if nested_time > 0.5:
            print("   ⚠️  DELAY: Deep nesting causes processing overhead!")
        
    except RecursionError:
        print("   ❌ STACK OVERFLOW: Deep nesting caused recursion error!")
        print("   This is a confirmed DoS vulnerability!")
    except Exception as e:
        print(f"   ERROR: {e}")
    
    # Vector 3: Many small nested objects
    print("\n3. Testing many small nested objects...")
    start_time = time.time()
    
    try:
        # Create 100,000 small nested objects
        nested_objects_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "many_objects": [{"id": i, "data": {"nested": {"value": i}}} for i in range(100000)]
        }
        
        json_str = json.dumps(nested_objects_payload)
        json_bytes = json_str.encode('utf-8')
        
        parsed = json.loads(json_bytes)
        
        objects_time = time.time() - start_time
        print(f"   Object count: {len(parsed['many_objects'])} objects")
        print(f"   Processing time: {objects_time:.2f} seconds")
        print(f"   JSON size: {len(json_bytes) / (1024*1024):.2f} MB")
        
        if objects_time > 2.0:
            print("   ⚠️  DELAY: Many objects cause significant processing!")
        
    except MemoryError:
        print("   ❌ MEMORY EXHAUSTED: Too many objects!")
    except Exception as e:
        print(f"   ERROR: {e}")
    
    # Vector 4: String explosion (repeated patterns that compress poorly)
    print("\n4. Testing string explosion payload...")
    start_time = time.time()
    
    try:
        # Create payload with many different strings (harder to compress/deduplicate)
        string_explosion_payload = {
            "messages": [{"role": "user", "content": "test"}],
            "many_strings": [f"unique_string_{i}_with_long_content_to_increase_memory_usage" for i in range(200000)]
        }
        
        json_str = json.dumps(string_explosion_payload)
        json_bytes = json_str.encode('utf-8')
        
        parsed = json.loads(json_bytes)
        
        strings_time = time.time() - start_time
        print(f"   String count: {len(parsed['many_strings'])} strings")
        print(f"   Processing time: {strings_time:.2f} seconds")
        print(f"   JSON size: {len(json_bytes) / (1024*1024):.2f} MB")
        
        if strings_time > 1.5:
            print("   ⚠️  DELAY: String explosion causes memory pressure!")
        
    except MemoryError:
        print("   ❌ MEMORY EXHAUSTED: Too many unique strings!")
    except Exception as e:
        print(f"   ERROR: {e}")
    
    print("\n" + "="*50)
    print("SUMMARY:")
    print("The ContentRewritingMiddleware is vulnerable to DoS attacks because:")
    print("1. No size limits on request.body() - accepts unlimited payload sizes")
    print("2. No validation before json.loads() - parses arbitrary JSON structures")
    print("3. No resource limits during processing - CPU/memory can be exhausted")
    print("4. No protection against malicious payloads (deep nesting, massive arrays)")
    print("="*50)


if __name__ == "__main__":
    test_json_dos_vectors()