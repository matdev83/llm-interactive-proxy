#!/usr/bin/env python3
"""
Final verification that DoS vulnerability is fixed.

This shows that:
1. Payloads over 10MB are rejected (✓ FIXED)
2. Deep nesting over 100 levels is rejected (✓ FIXED) 
3. Reasonable payloads still work (✓ GOOD)
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


def main():
    """Final verification of DoS fix."""
    print("DoS Vulnerability Fix Verification")
    print("=" * 50)
    
    parser = SSEBytesParser()
    
    print("\n1. Testing large payload protection:")
    # Test 15MB payload (should be rejected)
    large_payload = b'data: ' + b'{"data": "' + b'x' * (15 * 1024 * 1024) + b'"}'
    
    try:
        result = parser.parse(large_payload)
        print("   - Large payload (15MB) was NOT rejected - VULNERABLE!")
        return False
    except ValueError as e:
        if "too large" in str(e):
            print("   + Large payload (15MB) correctly rejected")
        else:
            print(f"   - Wrong rejection reason: {e}")
            return False
    
    print("\n2. Testing deep nesting protection:")
    # Test depth 150 (should be rejected)
    deep_json = create_deeply_nested_json(150)
    deep_payload = f"data: {deep_json}".encode('utf-8')
    
    try:
        result = parser.parse(deep_payload)
        print("   - Deep nesting (150 levels) was NOT rejected - VULNERABLE!")
        return False
    except ValueError as e:
        if "depth" in str(e).lower():
            print("   + Deep nesting (150 levels) correctly rejected")
        else:
            print(f"   - Wrong rejection reason: {e}")
            return False
    
    print("\n3. Testing normal functionality still works:")
    # Test normal payload (should work)
    normal_payload = b'data: {"message": "hello", "choices": [{"delta": {"content": "world"}}]}'
    
    try:
        result = parser.parse(normal_payload)
        if result.content and "hello" in str(result.content):
            print("   + Normal SSE payload works correctly")
        else:
            print("   - Normal payload parsing failed")
            return False
    except Exception as e:
        print(f"   - Normal payload rejected: {e}")
        return False
    
    print("\n4. Testing reasonable size limits:")
    # Test 5MB payload (should work - under 10MB limit)
    medium_json = '{"data": "' + 'x' * (5 * 1024 * 1024) + '"}'
    medium_payload = f"data: {medium_json}".encode('utf-8')
    
    try:
        result = parser.parse(medium_payload)
        print("   + 5MB payload accepted (under 10MB limit)")
    except Exception as e:
        print(f"   - 5MB payload rejected unexpectedly: {e}")
        return False
    
    print("\n" + "=" * 50)
    print("SUMMARY: DoS vulnerability is FIXED!")
    print("- Large payloads (>10MB) are rejected")
    print("- Deep nesting (>100 levels) is rejected") 
    print("- Normal functionality preserved")
    print("- Reasonable size limits (5MB < 10MB) work")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)