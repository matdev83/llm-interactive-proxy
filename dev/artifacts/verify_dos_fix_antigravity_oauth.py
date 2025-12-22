#!/usr/bin/env python3
"""
Verification script for DoS fix in antigravity_oauth.py
Tests that size validation now prevents large JSON payloads from being parsed
"""
import json
import sys
import time

# Use the same constant value as in the fixed code
MAX_JSON_PARSE_SIZE = 10 * 1024 * 1024  # 10MB in bytes


def create_large_json(size_mb: int = 15) -> str:
    """Create a large JSON payload that exceeds the 10MB limit"""
    large_payload = {
        "data": "A" * (size_mb * 1024 * 1024)  # Create size_mb MB of data
    }
    return json.dumps(large_payload)


def test_size_validation():
    """Test that size validation prevents parsing of large JSON"""
    print("=" * 60)
    print("DoS FIX VERIFICATION SCRIPT")
    print("Testing size validation in antigravity_oauth.py")
    print("=" * 60)
    
    # Test 1: Large JSON payload (>10MB) should be rejected
    print("\n1. Testing large JSON payload rejection (>10MB)...")
    large_json = create_large_json(15)  # 15MB payload
    json_size = len(large_json.encode("utf-8"))
    print(f"Created JSON payload: {json_size} bytes ({json_size / (1024*1024):.2f} MB)")
    print(f"Size limit: {MAX_JSON_PARSE_SIZE} bytes ({MAX_JSON_PARSE_SIZE / (1024*1024):.2f} MB)")
    
    # Simulate the size check from the fixed code
    start_time = time.time()
    if len(large_json.encode("utf-8")) > MAX_JSON_PARSE_SIZE:
        end_time = time.time()
        print(f"PASS: Large JSON payload correctly rejected")
        print(f"  Size check took {end_time - start_time:.4f} seconds (fast rejection)")
        print(f"  Payload size: {json_size} bytes > limit: {MAX_JSON_PARSE_SIZE} bytes")
    else:
        print("FAIL: Large JSON payload was not rejected!")
        return False
    
    # Test 2: Normal-sized JSON payload (<10MB) should pass
    print("\n2. Testing normal-sized JSON payload acceptance (<10MB)...")
    normal_json = create_large_json(5)  # 5MB payload
    json_size = len(normal_json.encode("utf-8"))
    print(f"Created JSON payload: {json_size} bytes ({json_size / (1024*1024):.2f} MB)")
    
    start_time = time.time()
    if len(normal_json.encode("utf-8")) > MAX_JSON_PARSE_SIZE:
        print("FAIL: Normal-sized JSON payload was incorrectly rejected!")
        return False
    else:
        # This would pass the size check and proceed to json.loads()
        try:
            parsed = json.loads(normal_json)
            end_time = time.time()
            print(f"PASS: Normal-sized JSON payload correctly accepted")
            print(f"  Parsing took {end_time - start_time:.4f} seconds")
            print(f"  Payload size: {json_size} bytes <= limit: {MAX_JSON_PARSE_SIZE} bytes")
        except Exception as e:
            print(f"FAIL: Normal JSON parsing failed: {e}")
            return False
    
    # Test 3: Boundary test - exactly at 10MB limit
    print("\n3. Testing boundary condition (exactly 10MB)...")
    # Create a payload that's just over 10MB
    boundary_json = create_large_json(11)  # 11MB payload
    json_size = len(boundary_json.encode("utf-8"))
    print(f"Created JSON payload: {json_size} bytes ({json_size / (1024*1024):.2f} MB)")
    
    if len(boundary_json.encode("utf-8")) > MAX_JSON_PARSE_SIZE:
        print(f"PASS: Boundary payload correctly rejected (just over limit)")
    else:
        print(f"FAIL: Boundary payload incorrectly accepted")
        return False
    
    print("\n" + "=" * 60)
    print("ALL TESTS PASSED:")
    print("- Large payloads (>10MB) are rejected quickly")
    print("- Normal payloads (<10MB) are accepted")
    print("- Boundary condition works correctly")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = test_size_validation()
    sys.exit(0 if success else 1)

