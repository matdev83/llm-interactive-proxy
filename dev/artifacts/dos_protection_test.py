#!/usr/bin/env python3
"""
Test script to verify DoS protection fixes in SSEBytesParser.

This script verifies that:
1. Large payloads are rejected
2. Deeply nested JSON is rejected
3. Normal payloads still work correctly
"""

import json
import sys
import time
from pathlib import Path

# Add src to path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from src.core.domain.streaming.parsing.sse_bytes_parser import SSEBytesParser


def create_deeply_nested_json(depth: int) -> str:
    """Create a deeply nested JSON structure."""
    result = {"payload": "data"}
    for _ in range(depth):
        result = {"nested": result}
    return json.dumps(result)


def create_large_json(size_mb: int) -> str:
    """Create a large JSON payload."""
    large_array = []
    target_size = size_mb * 1024 * 1024
    
    obj_count = min(target_size // 100, 1000000)
    
    for i in range(obj_count):
        large_array.append({
            "id": i,
            "data": "x" * 50,
            "value": 42,
        })
    
    return json.dumps(large_array)


def test_protection_against_large_payloads():
    """Test that large payloads are rejected."""
    print("=== Testing Protection Against Large Payloads ===")
    
    parser = SSEBytesParser()
    
    # Test payload just under limit (should work)
    normal_payload = '{"message": "hello"}'.encode('utf-8')
    try:
        result = parser.parse(normal_payload)
        print("+ Normal payload accepted")
    except Exception as e:
        print(f"- Normal payload rejected: {e}")
        return False
    
    # Test payload over limit (should be rejected)
    large_json = create_large_json(15)  # 15MB > 10MB limit
    large_payload = f"data: {large_json}".encode('utf-8')
    
    try:
        result = parser.parse(large_payload)
        print("- Large payload was accepted - VULNERABLE!")
        return False
    except ValueError as e:
        if "too large" in str(e):
            print("+ Large payload correctly rejected")
            return True
        else:
            print(f"- Large payload rejected for wrong reason: {e}")
            return False
    except Exception as e:
        print(f"- Unexpected error: {e}")
        return False


def test_protection_against_deep_nesting():
    """Test that deeply nested JSON is rejected."""
    print("\n=== Testing Protection Against Deep Nesting ===")
    
    parser = SSEBytesParser()
    
    # Test normal depth (should work)
    normal_json = create_deeply_nested_json(10)
    normal_payload = f"data: {normal_json}".encode('utf-8')
    
    try:
        result = parser.parse(normal_payload)
        print("+ Normal depth JSON accepted")
    except Exception as e:
        print(f"- Normal depth JSON rejected: {e}")
        return False
    
    # Test excessive depth (should be rejected)
    deep_json = create_deeply_nested_json(150)  # > 100 limit
    deep_payload = f"data: {deep_json}".encode('utf-8')
    
    try:
        result = parser.parse(deep_payload)
        print("- Deep JSON was accepted - VULNERABLE!")
        return False
    except Exception as e:
        if "depth" in str(e).lower() or "too deeply nested" in str(e).lower():
            print("+ Deep JSON correctly rejected")
            return True
        else:
            print(f"- Deep JSON rejected for wrong reason: {e}")
            return False


def test_normal_functionality():
    """Test that normal functionality still works."""
    print("\n=== Testing Normal Functionality ===")
    
    parser = SSEBytesParser()
    
    # Test SSE with [DONE]
    try:
        result = parser.parse(b"data: [DONE]")
        if result.is_done:
            print("+ SSE [DONE] marker works")
        else:
            print("- SSE [DONE] marker not recognized")
            return False
    except Exception as e:
        print(f"- SSE [DONE] failed: {e}")
        return False
    
    # Test SSE with JSON
    try:
        test_json = '{"choices": [{"delta": {"content": "hello"}}]}'
        result = parser.parse(f"data: {test_json}".encode('utf-8'))
        if result.content and "hello" in str(result.content):
            print("+ SSE JSON parsing works")
        else:
            print("- SSE JSON parsing failed")
            return False
    except Exception as e:
        print(f"- SSE JSON parsing failed: {e}")
        return False
    
    # Test plain string (non-SSE)
    try:
        result = parser.parse(b"plain text")
        if result.content == "plain text":
            print("+ Plain string parsing works")
        else:
            print("- Plain string parsing failed")
            return False
    except Exception as e:
        print(f"- Plain string parsing failed: {e}")
        return False
    
    return True


def test_edge_cases():
    """Test edge cases."""
    print("\n=== Testing Edge Cases ===")
    
    parser = SSEBytesParser()
    
    # Test empty payload
    try:
        result = parser.parse(b"")
        print("+ Empty payload handled")
    except Exception as e:
        print(f"- Empty payload failed: {e}")
        return False
    
    # Test invalid UTF-8
    try:
        result = parser.parse(b'\xff\xfe\x00\x00')  # Invalid UTF-8
        print("+ Invalid UTF-8 handled")
    except Exception as e:
        print(f"- Invalid UTF-8 failed: {e}")
        return False
    
    # Test malformed JSON
    try:
        result = parser.parse(b"data: {invalid json}")
        # Should fall back to plain string
        if "{invalid json}" in result.content:
            print("+ Malformed JSON falls back to string")
        else:
            print("- Malformed JSON not handled correctly")
            return False
    except Exception as e:
        print(f"- Malformed JSON failed: {e}")
        return False
    
    return True


def main():
    """Run all protection tests."""
    print("DoS Protection Verification: SSEBytesParser")
    print("=" * 60)
    
    tests_passed = 0
    total_tests = 4
    
    if test_protection_against_large_payloads():
        tests_passed += 1
    
    if test_protection_against_deep_nesting():
        tests_passed += 1
    
    if test_normal_functionality():
        tests_passed += 1
    
    if test_edge_cases():
        tests_passed += 1
    
    print(f"\n{'='*60}")
    print(f"RESULTS: {tests_passed}/{total_tests} protection tests passed")
    
    if tests_passed == total_tests:
        print("+ All DoS protections working correctly!")
        return True
    else:
        print("- Some protections are not working correctly")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)