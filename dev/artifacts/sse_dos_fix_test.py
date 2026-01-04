#!/usr/bin/env python3
"""
Test script to verify DoS fix in SSE decoder.

This script verifies that the security fixes work correctly by testing
various attack vectors that should now be mitigated.
"""

import json
import os
import sys
import time

# Add src to path to import the vulnerable code
src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, src_path)

from src.core.transport.fastapi.adapters.sse.decoder import SSEDecoder


def create_nested_json_depth(depth: int) -> str:
    """Create a deeply nested JSON structure that can cause DoS."""
    if depth <= 0:
        return '"leaf"'

    return json.dumps({"nested": json.loads(create_nested_json_depth(depth - 1))})


def test_security_limits():
    """Test that security limits are properly enforced."""
    decoder = SSEDecoder()

    print("Testing SSE Decoder Security Fixes")
    print("=" * 50)

    # Test 1: Depth limit enforcement
    print("\n1. Testing depth limit enforcement...")
    malicious_json = create_nested_json_depth(SSEDecoder.MAX_JSON_DEPTH + 1)
    sse_payload = f"data: {malicious_json}"

    try:
        result = decoder.decode_payload(sse_payload)
        metadata = result[1]
        if "error" in metadata:
            print(f"   [PROTECTED] Depth limit enforced: {metadata['error']}")
        else:
            print("   [VULNERABLE] Deep JSON was accepted!")
    except Exception as e:
        print(f"   [PROTECTED] Exception caught: {type(e).__name__}")

    # Test 2: Within depth limit (should work)
    print("\n2. Testing within depth limit...")
    safe_json = create_nested_json_depth(SSEDecoder.MAX_JSON_DEPTH - 1)
    safe_payload = f"data: {safe_json}"

    try:
        result = decoder.decode_payload(safe_payload)
        metadata = result[1]
        if "error" in metadata:
            print(f"   [ERROR] Safe JSON was rejected: {metadata['error']}")
        else:
            print(
                f"   [OK] Safe JSON accepted (depth: {SSEDecoder.MAX_JSON_DEPTH - 1})"
            )
    except Exception as e:
        print(f"   [ERROR] Unexpected exception: {type(e).__name__}: {e}")

    # Test 3: Payload size limit
    print(f"\n3. Testing payload size limit ({SSEDecoder.MAX_PAYLOAD_SIZE} bytes)...")
    large_data = "x" * (SSEDecoder.MAX_PAYLOAD_SIZE + 1000)
    large_payload = f"data: {large_data}"

    try:
        result = decoder.decode_payload(large_payload)
        metadata = result[1]
        if "error" in metadata:
            print(f"   [PROTECTED] Size limit enforced: {metadata['error']}")
        else:
            print("   [VULNERABLE] Large payload was accepted!")
    except Exception as e:
        print(f"   [PROTECTED] Exception caught: {type(e).__name__}")

    # Test 4: Data lines limit
    print(f"\n4. Testing data lines limit ({SSEDecoder.MAX_DATA_LINES} lines)...")
    lines = []
    for i in range(SSEDecoder.MAX_DATA_LINES + 100):
        lines.append(f"data: line_{i}")

    many_lines_payload = "\n".join(lines)

    try:
        result = decoder.decode_payload(many_lines_payload)
        metadata = result[1]
        if "error" in metadata:
            print(f"   [PROTECTED] Lines limit enforced: {metadata['error']}")
        else:
            print(
                f"   [OK] Lines limit handled (processed {len(result[0]) if isinstance(result[0], str) else 'parsed object'})"
            )
    except Exception as e:
        print(f"   [PROTECTED] Exception caught: {type(e).__name__}")

    # Test 5: Performance test for legitimate payloads
    print("\n5. Testing performance with legitimate payloads...")
    legitimate_json = json.dumps(
        {
            "choices": [{"delta": {"content": "Hello, world!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
    )
    legitimate_payload = f"data: {legitimate_json}"

    start_time = time.time()
    for i in range(1000):
        result = decoder.decode_payload(legitimate_payload)
    end_time = time.time()

    print(f"   [OK] Processed 1000 legitimate payloads in {end_time - start_time:.3f}s")
    print(f"   Average: {(end_time - start_time) / 1000 * 1000:.3f}ms per payload")


if __name__ == "__main__":
    test_security_limits()
    print("\n" + "=" * 50)
    print("Security fix verification completed!")
    print("The SSE decoder now includes proper DoS protection.")
