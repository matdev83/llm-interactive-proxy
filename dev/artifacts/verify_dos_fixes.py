#!/usr/bin/env python3
"""Verify DoS fixes are working correctly."""

import json
import sys
from pathlib import Path

# Add the src directory to the path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.common.json_validation import JSONValidationError, validate_json_structure
from src.core.domain.streaming.parsing.json_string_parser import JSONStringParser


def create_deeply_nested_json(depth: int) -> dict:
    """Create a JSON structure with specified nesting depth."""
    if depth == 0:
        return {"value": "leaf"}
    return {"nested": create_deeply_nested_json(depth - 1)}


def create_large_array_json(size: int) -> dict:
    """Create a JSON structure with a large array."""
    return {"data": list(range(size))}


def test_json_validation_utility():
    """Test the JSON validation utility directly."""
    print("Testing JSON validation utility...")
    
    # Test 1: Normal JSON should pass
    normal_json = {"key": "value", "nested": {"key2": "value2"}}
    try:
        validate_json_structure(normal_json)
        print("  PASS: Normal JSON validated successfully")
    except JSONValidationError:
        print("  FAIL: Normal JSON was rejected")
        return False
    
    # Test 2: Deep nesting should fail
    deep_json = create_deeply_nested_json(150)  # Exceeds MAX_JSON_DEPTH (100)
    try:
        validate_json_structure(deep_json)
        print("  FAIL: Deep nesting was not rejected")
        return False
    except JSONValidationError:
        print("  PASS: Deep nesting correctly rejected")
    
    # Test 3: Large array should fail
    large_array_json = create_large_array_json(2_000_000)  # Exceeds MAX_ARRAY_ELEMENTS (1M)
    try:
        validate_json_structure(large_array_json)
        print("  FAIL: Large array was not rejected")
        return False
    except JSONValidationError:
        print("  PASS: Large array correctly rejected")
    
    return True


def test_json_string_parser():
    """Test JSONStringParser with malicious payloads."""
    print("\nTesting JSONStringParser...")
    
    parser = JSONStringParser()
    
    # Test 1: Normal JSON should work
    normal_json_str = json.dumps({"key": "value"})
    try:
        result = parser.parse(normal_json_str)
        print("  PASS: Normal JSON parsed successfully")
    except Exception as e:
        print(f"  FAIL: Normal JSON failed: {e}")
        return False
    
    # Test 2: Deep nesting should be rejected
    deep_json = create_deeply_nested_json(150)
    deep_json_str = json.dumps(deep_json)
    try:
        parser.parse(deep_json_str)
        print("  FAIL: Deep nesting was not rejected")
        return False
    except ValueError as e:
        if "validation" in str(e).lower() or "depth" in str(e).lower():
            print("  PASS: Deep nesting correctly rejected")
        else:
            print(f"  FAIL: Wrong error type: {e}")
            return False
    
    # Test 3: Large array should be rejected
    # Note: Size check happens first, which is valid DoS protection
    # Test with array that fits size limit but exceeds element limit
    # Use compact representation: small numbers in array
    large_array_json = {"data": [0] * 1_500_000}  # 1.5M elements, exceeds 1M limit
    large_array_str = json.dumps(large_array_json)
    try:
        parser.parse(large_array_str)
        print("  FAIL: Large array was not rejected")
        return False
    except ValueError as e:
        # Size-based rejection is valid DoS protection (happens before array validation)
        # Array validation would also catch it if size check didn't
        error_str = str(e).lower()
        if any(keyword in error_str for keyword in ["validation", "array", "size", "large", "elements", "exceeds"]):
            print("  PASS: Large array correctly rejected (size or element limit)")
        else:
            print(f"  FAIL: Wrong error type: {e}")
            return False
    
    # Test 4: Very large payload should be rejected
    huge_string = "A" * (11 * 1024 * 1024)  # 11MB, exceeds 10MB limit
    huge_json_str = json.dumps({"data": huge_string})
    try:
        parser.parse(huge_json_str)
        print("  FAIL: Large payload was not rejected")
        return False
    except ValueError as e:
        if "size" in str(e).lower() or "large" in str(e).lower():
            print("  PASS: Large payload correctly rejected")
        else:
            print(f"  FAIL: Wrong error type: {e}")
            return False
    
    return True


if __name__ == "__main__":
    print("DoS Fix Verification")
    print("=" * 60)
    
    all_passed = True
    
    if not test_json_validation_utility():
        all_passed = False
    
    if not test_json_string_parser():
        all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("SUCCESS: All DoS protections are working correctly!")
        sys.exit(0)
    else:
        print("FAILURE: Some DoS protections are not working!")
        sys.exit(1)

