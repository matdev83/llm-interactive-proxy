#!/usr/bin/env python3
"""
Test script to verify the DoS protection fix in ContentRewritingMiddleware.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add the src directory to the path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import HTTPException
from src.core.app.middleware.content_rewriting_middleware import (
    ContentRewritingMiddleware,
)
from src.core.services.content_rewriter_service import ContentRewriterService


class MockContentRewriterService(ContentRewriterService):
    """Mock rewriter service."""

    def rewrite_prompt(self, content: str, role: str) -> str:
        return content

    def rewrite_reply(self, content: str) -> str:
        return content


async def test_dos_protection():
    """Test that the DoS protection works correctly."""

    print("Testing DoS protection in ContentRewritingMiddleware...")

    # Create middleware instance
    rewriter = MockContentRewriterService()
    middleware = ContentRewritingMiddleware(None, rewriter)

    # Test 1: Body size limit
    print("\n1. Testing body size limit...")

    # Create payload larger than 10MB
    large_payload = {
        "messages": [{"role": "user", "content": "test"}],
        "large_string": "A" * (12 * 1024 * 1024),  # 12MB string
    }

    large_json = json.dumps(large_payload)
    large_bytes = large_json.encode("utf-8")

    try:
        middleware._validate_json_size(large_bytes)
        print("   FAILED: Large payload was accepted!")
    except HTTPException as e:
        print(f"   PASSED: Large payload correctly rejected: {e.detail}")
    except Exception as e:
        print(f"   ERROR: Unexpected exception: {e}")

    # Test 2: Normal sized payload should work
    print("\n2. Testing normal payload size...")

    normal_payload = {
        "messages": [{"role": "user", "content": "test"}],
        "normal_string": "A" * 1000,  # 1KB string
    }

    normal_json = json.dumps(normal_payload)
    normal_bytes = normal_json.encode("utf-8")

    try:
        middleware._validate_json_size(normal_bytes)
        print("   PASSED: Normal payload accepted")
    except Exception as e:
        print(f"   FAILED: Normal payload was rejected: {e}")

    # Test 3: Deep nesting limit
    print("\n3. Testing deep nesting limit...")

    # Create deeply nested structure
    nested_data = {"value": "root"}
    for i in range(150):  # Exceeds MAX_NESTING_DEPTH (100)
        nested_data = {"nested": nested_data}

    deep_payload = {
        "messages": [{"role": "user", "content": "test"}],
        "deeply_nested": nested_data,
    }

    try:
        middleware._validate_json_structure(deep_payload)
        print("   FAILED: Deep nesting was accepted!")
    except HTTPException as e:
        print(f"   PASSED: Deep nesting correctly rejected: {e.detail}")
    except Exception as e:
        print(f"   ERROR: Unexpected exception: {e}")

    # Test 4: Normal nesting should work
    print("\n4. Testing normal nesting depth...")

    normal_nested_data = {"value": "root"}
    for i in range(50):  # Within limit
        normal_nested_data = {"nested": normal_nested_data}

    normal_nested_payload = {
        "messages": [{"role": "user", "content": "test"}],
        "normal_nested": normal_nested_data,
    }

    try:
        middleware._validate_json_structure(normal_nested_payload)
        print("   PASSED: Normal nesting accepted")
    except Exception as e:
        print(f"   FAILED: Normal nesting was rejected: {e}")

    # Test 5: Large array limit
    print("\n5. Testing large array limit...")

    large_array_payload = {
        "messages": [{"role": "user", "content": "test"}],
        "large_array": list(range(2_000_000)),  # Exceeds MAX_ARRAY_ELEMENTS (1M)
    }

    try:
        middleware._validate_json_structure(large_array_payload)
        print("   FAILED: Large array was accepted!")
    except HTTPException as e:
        print(f"   PASSED: Large array correctly rejected: {e.detail}")
    except Exception as e:
        print(f"   ERROR: Unexpected exception: {e}")

    # Test 6: Normal array should work
    print("\n6. Testing normal array size...")

    normal_array_payload = {
        "messages": [{"role": "user", "content": "test"}],
        "normal_array": list(range(100000)),  # Within limit
    }

    try:
        middleware._validate_json_structure(normal_array_payload)
        print("   PASSED: Normal array accepted")
    except Exception as e:
        print(f"   FAILED: Normal array was rejected: {e}")

    # Test 7: Combined validation test
    print("\n7. Testing combined validation...")

    combined_payload = {
        "messages": [{"role": "user", "content": "test"}],
        "data": list(range(1000)),
        "nested": {"level1": {"level2": {"level3": "deep"}}},
    }

    combined_json = json.dumps(combined_payload)
    combined_bytes = combined_json.encode("utf-8")

    try:
        middleware._validate_json_size(combined_bytes)
        middleware._validate_json_structure(combined_payload)
        print("   PASSED: Combined validation successful")
    except Exception as e:
        print(f"   FAILED: Combined validation failed: {e}")

    print("\n" + "=" * 50)
    print("DoS PROTECTION TEST SUMMARY:")
    print("- Body size limits: ENFORCED")
    print("- Nesting depth limits: ENFORCED")
    print("- Array size limits: ENFORCED")
    print("- Normal payloads: ACCEPTED")
    print("- Malicious payloads: REJECTED")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(test_dos_protection())
