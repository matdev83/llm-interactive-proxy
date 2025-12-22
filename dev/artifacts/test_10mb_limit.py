#!/usr/bin/env python3
"""
Simple test to verify 10MB limit is working correctly with valid JSON.
"""

import json
import sys
from pathlib import Path

# Add src directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.tool_call_repair_service import MAX_JSON_PARSE_SIZE, ToolCallRepairService

def test_size_limit():
    """Test that 10MB limit is working."""
    print(f"Testing with MAX_JSON_PARSE_SIZE = {MAX_JSON_PARSE_SIZE} bytes ({MAX_JSON_PARSE_SIZE/1024/1024}MB)")
    
    repair_service = ToolCallRepairService()
    
    # Test 1: Small payload (should work)
    small_payload = '{"function_call": {"name": "test", "arguments": {"test": "small"}}'
    print(f"\nTest 1 - Small payload ({len(small_payload)} chars):")
    
    result = repair_service.repair_tool_calls(f"```json\n{small_payload}\n```")
    if result:
        print("  [OK] Small payload processed successfully")
    else:
        print("  [FAIL] Small payload rejected")
    
    # Test 2: Medium payload (should work)
    # Create valid JSON with many small items
    medium_data = {
        "function_call": {
            "name": "test",
            "arguments": {
                "items": [{"id": i, "value": f"item_{i}"} for i in range(50000)]
            }
        }
    }
    medium_payload = json.dumps(medium_data)
    medium_size_mb = len(medium_payload.encode('utf-8')) / (1024 * 1024)
    print(f"\nTest 2 - Medium payload ({medium_size_mb:.2f}MB):")
    
    result = repair_service.repair_tool_calls(f"```json\n{medium_payload}\n```")
    if result:
        print("  [OK] Medium payload processed successfully")
    else:
        print("  [FAIL] Medium payload rejected")
    
    # Test 3: Large payload (should be blocked)
    # Create valid JSON that exceeds 10MB
    large_data = {
        "function_call": {
            "name": "test",
            "arguments": {
                "items": [{"id": i, "value": "x" * 100} for i in range(800000)]  # Much larger
            }
        }
    }
    large_payload = json.dumps(large_data)
    large_size_mb = len(large_payload.encode('utf-8')) / (1024 * 1024)
    print(f"\nTest 3 - Large payload ({large_size_mb:.2f}MB):")
    
    result = repair_service.repair_tool_calls(f"```json\n{large_payload}\n```")
    if result is None:
        print("  [OK] Large payload correctly rejected")
    else:
        print("  [FAIL] Large payload was not rejected")
    
    # Test 4: Just under 10MB (should work)
    under_data = {
        "function_call": {
            "name": "test",
            "arguments": {
                "items": [{"id": i, "value": "x" * 50} for i in range(150000)]  # Just under limit
            }
        }
    }
    under_payload = json.dumps(under_data)
    under_size_mb = len(under_payload.encode('utf-8')) / (1024 * 1024)
    print(f"\nTest 4 - Under 10MB payload ({under_size_mb:.2f}MB):")
    
    result = repair_service.repair_tool_calls(f"```json\n{under_payload}\n```")
    if result:
        print("  [OK] Under 10MB payload processed successfully")
    else:
        print("  [FAIL] Under 10MB payload rejected")
    
    # Test 5: Just over 10MB (should be rejected)
    over_data = {
        "function_call": {
            "name": "test",
            "arguments": {
                "items": [{"id": i, "value": "x" * 50} for i in range(170000)]  # Just over limit
            }
        }
    }
    over_payload = json.dumps(over_data)
    over_size_mb = len(over_payload.encode('utf-8')) / (1024 * 1024)
    print(f"\nTest 5 - Over 10MB payload ({over_size_mb:.2f}MB):")
    
    result = repair_service.repair_tool_calls(f"```json\n{over_payload}\n```")
    if result is None:
        print("  [OK] Over 10MB payload correctly rejected")
    else:
        print("  [FAIL] Over 10MB payload was not rejected")

if __name__ == "__main__":
    test_size_limit()
    
    print("\n=== Summary ===")
    print("Expected results:")
    print("- Small and medium payloads: Should work")
    print("- Under 10MB payload: Should work") 
    print("- Over 10MB payload: Should be rejected")
    print("\nIf over 10MB payload is not rejected, protection is not working correctly.")