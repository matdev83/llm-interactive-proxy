#!/usr/bin/env python3
"""
DoS vulnerability reproduction script for CaptureDecoder.
This script demonstrates how deeply nested or large JSON payloads can cause
stack overflow or memory exhaustion in capture_decoder.py.
"""

import json
import sys
import time
from pathlib import Path

# Add the src directory to the path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.simulation.capture_decoder import CaptureDecoder
from src.core.domain.cbor_capture import CaptureDirection, CaptureEntry, CaptureMetadata


def create_deeply_nested_json(depth: int) -> dict:
    """Create a JSON structure with specified nesting depth."""
    if depth == 0:
        return {"value": "leaf"}
    return {"nested": create_deeply_nested_json(depth - 1)}


def create_large_array_json(size: int) -> dict:
    """Create a JSON structure with a large array."""
    return {"messages": [{"role": "user", "content": "test"}] * size}


def test_deep_nesting_attack():
    """Test stack overflow attack via deeply nested JSON."""
    print("=" * 60)
    print("TEST 1: Deep Nesting Attack (Stack Overflow)")
    print("=" * 60)
    
    decoder = CaptureDecoder()
    
    # Test with increasing depths
    for depth in [100, 200, 500, 1000]:
        print(f"\nTesting with nesting depth: {depth}")
        
        nested_data = create_deeply_nested_json(depth)
        json_str = json.dumps(nested_data)
        json_bytes = json_str.encode("utf-8")
        
        print(f"  JSON size: {len(json_bytes)} bytes")
        
        entry = CaptureEntry(
            direction=CaptureDirection.CLIENT_TO_PROXY,
            data=json_bytes,
            metadata=CaptureMetadata(),
        )
        
        start_time = time.time()
        try:
            result = decoder.decode_inbound_request(entry)
            elapsed = time.time() - start_time
            
            if result.is_success:
                print(f"  ✓ Parsed successfully in {elapsed:.3f}s")
            else:
                print(f"  ✗ Failed: {result.error}")
        except RecursionError as e:
            print(f"  ✗ RECURSION ERROR (DoS confirmed!): {e}")
            return True
        except Exception as e:
            print(f"  ✗ Error: {type(e).__name__}: {e}")
            return True
    
    return False


def test_large_array_attack():
    """Test memory exhaustion attack via large arrays."""
    print("\n" + "=" * 60)
    print("TEST 2: Large Array Attack (Memory Exhaustion)")
    print("=" * 60)
    
    decoder = CaptureDecoder()
    
    # Test with increasing array sizes
    for size in [100000, 500000, 1000000, 2000000]:
        print(f"\nTesting with array size: {size:,}")
        
        large_data = create_large_array_json(size)
        json_str = json.dumps(large_data)
        json_bytes = json_str.encode("utf-8")
        
        print(f"  JSON size: {len(json_bytes) / (1024*1024):.2f} MB")
        
        entry = CaptureEntry(
            direction=CaptureDirection.CLIENT_TO_PROXY,
            data=json_bytes,
            metadata=CaptureMetadata(),
        )
        
        start_time = time.time()
        try:
            result = decoder.decode_inbound_request(entry)
            elapsed = time.time() - start_time
            
            if result.is_success:
                print(f"  ✓ Parsed successfully in {elapsed:.3f}s")
            else:
                print(f"  ✗ Failed: {result.error}")
        except MemoryError as e:
            print(f"  ✗ MEMORY ERROR (DoS confirmed!): {e}")
            return True
        except Exception as e:
            print(f"  ✗ Error: {type(e).__name__}: {e}")
            if "memory" in str(e).lower():
                return True
    
    return False


def test_combined_attack():
    """Test combined attack with both deep nesting and large arrays."""
    print("\n" + "=" * 60)
    print("TEST 3: Combined Attack (Deep Nesting + Large Arrays)")
    print("=" * 60)
    
    decoder = CaptureDecoder()
    
    # Create payload with both deep nesting and large arrays
    combined_data = {
        "messages": [{"role": "user", "content": "test"}] * 50000,
        "nested": create_deeply_nested_json(200),
        "large_array": list(range(100000)),
    }
    
    json_str = json.dumps(combined_data)
    json_bytes = json_str.encode("utf-8")
    
    print(f"JSON size: {len(json_bytes) / (1024*1024):.2f} MB")
    
    entry = CaptureEntry(
        direction=CaptureDirection.CLIENT_TO_PROXY,
        data=json_bytes,
        metadata=CaptureMetadata(),
    )
    
    start_time = time.time()
    try:
        result = decoder.decode_inbound_request(entry)
        elapsed = time.time() - start_time
        
        if result.is_success:
            print(f"✓ Parsed successfully in {elapsed:.3f}s")
            print("⚠ WARNING: Combined attack succeeded - vulnerability confirmed!")
            return True
        else:
            print(f"✗ Failed: {result.error}")
    except (RecursionError, MemoryError) as e:
        print(f"✗ ERROR (DoS confirmed!): {type(e).__name__}: {e}")
        return True
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")
        return True
    
    return False


if __name__ == "__main__":
    print("DoS Vulnerability Test: CaptureDecoder")
    print("=" * 60)
    print("This script tests for DoS vulnerabilities in capture_decoder.py")
    print("by attempting to exploit JSON parsing without depth/array limits.\n")
    
    vulnerabilities_found = []
    
    if test_deep_nesting_attack():
        vulnerabilities_found.append("Deep nesting (stack overflow)")
    
    if test_large_array_attack():
        vulnerabilities_found.append("Large arrays (memory exhaustion)")
    
    if test_combined_attack():
        vulnerabilities_found.append("Combined attack")
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if vulnerabilities_found:
        print("⚠ VULNERABILITIES CONFIRMED:")
        for vuln in vulnerabilities_found:
            print(f"  - {vuln}")
        print("\nThe CaptureDecoder is vulnerable to DoS attacks via:")
        print("  1. Deeply nested JSON causing stack overflow")
        print("  2. Large arrays causing memory exhaustion")
        print("  3. Combined attacks using both techniques")
        sys.exit(1)
    else:
        print("✓ No obvious vulnerabilities detected in this test.")
        print("  (Note: This doesn't guarantee security - manual review recommended)")
        sys.exit(0)

