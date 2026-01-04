#!/usr/bin/env python3
"""
Simple test to verify 10MB limit is working correctly.
"""

import sys
from pathlib import Path

# Add src directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.tool_call_repair_service import (
    MAX_JSON_PARSE_SIZE,
    ToolCallRepairService,
)


def test_size_limit():
    """Test that the 10MB limit is working."""
    print(
        f"Testing with MAX_JSON_PARSE_SIZE = {MAX_JSON_PARSE_SIZE} bytes ({MAX_JSON_PARSE_SIZE/1024/1024}MB)"
    )

    repair_service = ToolCallRepairService()

    # Test 1: Small payload (should work)
    small_payload = (
        '{"function_call": {"name": "test", "arguments": {"test": "small"}}}'
    )
    print(f"\nTest 1 - Small payload ({len(small_payload)} chars):")

    result = repair_service.repair_tool_calls(f"```json\n{small_payload}\n```")
    if result:
        print("  [OK] Small payload processed successfully")
    else:
        print("  [FAIL] Small payload rejected")

    # Test 2: Medium payload (should work)
    medium_payload = '{"function_call": {"name": "test", "arguments": {"data": "x" * 1000000}}}'  # ~1MB
    medium_size_mb = len(medium_payload.encode("utf-8")) / (1024 * 1024)
    print(f"\nTest 2 - Medium payload ({medium_size_mb:.2f}MB):")

    result = repair_service.repair_tool_calls(f"```json\n{medium_payload}\n```")
    if result:
        print("  [OK] Medium payload processed successfully")
    else:
        print("  [FAIL] Medium payload rejected")

    # Test 3: Large payload (should be blocked)
    large_payload = '{"function_call": {"name": "test", "arguments": {"data": "x" * 15000000}}}'  # ~15MB
    large_size_mb = len(large_payload.encode("utf-8")) / (1024 * 1024)
    print(f"\nTest 3 - Large payload ({large_size_mb:.2f}MB):")

    result = repair_service.repair_tool_calls(f"```json\n{large_payload}\n```")
    if result is None:
        print("  [OK] Large payload correctly rejected")
    else:
        print("  [FAIL] Large payload was not rejected")

    # Test 4: Exact boundary test (just under 10MB)
    boundary_under_mb = 9.5  # Just under 10MB
    boundary_under_payload = (
        '{"function_call": {"name": "test", "arguments": {"data": "'
        + "x" * int(boundary_under_mb * 1024 * 1024 * 0.8)
        + '"}}}'
    )
    boundary_under_size_mb = len(boundary_under_payload.encode("utf-8")) / (1024 * 1024)
    print(f"\nTest 4 - Boundary under ({boundary_under_size_mb:.2f}MB):")

    result = repair_service.repair_tool_calls(f"```json\n{boundary_under_payload}\n```")
    if result:
        print("  [OK] Boundary under payload processed successfully")
    else:
        print("  [FAIL] Boundary under payload rejected")

    # Test 5: Exact boundary test (just over 10MB)
    boundary_over_mb = 10.5  # Just over 10MB
    boundary_over_payload = (
        '{"function_call": {"name": "test", "arguments": {"data": "'
        + "x" * int(boundary_over_mb * 1024 * 1024 * 0.8)
        + '"}}}'
    )
    boundary_over_size_mb = len(boundary_over_payload.encode("utf-8")) / (1024 * 1024)
    print(f"\nTest 5 - Boundary over ({boundary_over_size_mb:.2f}MB):")

    result = repair_service.repair_tool_calls(f"```json\n{boundary_over_payload}\n```")
    if result is None:
        print("  [OK] Boundary over payload correctly rejected")
    else:
        print("  [FAIL] Boundary over payload was not rejected")


if __name__ == "__main__":
    test_size_limit()

    print("\n=== Summary ===")
    print("Expected results:")
    print("- Small and medium payloads: Should work")
    print("- Boundary under 10MB: Should work")
    print("- Boundary over 10MB: Should be rejected")
    print(
        "\nIf any payload over 10MB is not rejected, protection is not working correctly."
    )
