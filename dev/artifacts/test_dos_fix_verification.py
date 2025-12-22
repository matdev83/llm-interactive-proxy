#!/usr/bin/env python3
"""
Test script to verify DoS fix for rate_limit.py and size limits
"""

import sys
import os
import time
import json

# Add src to path to import module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.rate_limit import _as_dict

def test_size_limits():
    """Test that size limits are now enforced."""
    
    print("Testing DoS protection fixes...")
    print("=" * 50)
    
    # Test 1: Normal sized input (should work)
    print("\nTest 1: Normal sized input (should work)")
    normal_input = '{"error": {"message": "Test error"}}'
    result = _as_dict(normal_input)
    print(f"Normal input result: {result is not None}")
    
    # Test 2: Exactly at limit (should work)
    print("\nTest 2: Input exactly at 10MB limit")
    large_input = '{"data": ["' + 'x' * (10 * 1024 * 1024 - 50) + '"]}'  # Just under 10MB
    result = _as_dict(large_input)
    print(f"At-limit input result: {result is not None}")
    
    # Test 3: Over limit (should be rejected)
    print("\nTest 3: Input over 10MB limit (should be rejected)")
    oversized_input = '{"data": ["' + 'x' * (10 * 1024 * 1024 + 1000) + '"]}'  # Over 10MB
    start_time = time.time()
    result = _as_dict(oversized_input)
    end_time = time.time()
    
    print(f"Oversized input result: {result is None}")
    print(f"Processing time: {end_time - start_time:.4f}s")
    
    if result is None and end_time - start_time < 0.1:
        print("SUCCESS: Oversized input properly rejected quickly")
        return True
    else:
        print("FAILURE: Oversized input was not properly rejected")
        return False

def test_functional_behavior():
    """Test that normal functionality still works."""
    
    print("\nTesting normal functionality...")
    print("-" * 30)
    
    test_cases = [
        # Valid JSON dict
        '{"error": {"code": 500, "message": "Internal error"}}',
        
        # JSON with embedded JSON
        'Some text {"nested": {"data": "value"}} more text',
        
        # Invalid JSON
        '{"invalid": json structure',
        
        # Empty string
        '',
        
        # Non-string input
        {"already": "dict"},
        
        # None
        None,
    ]
    
    expected_results = [True, True, False, False]
    passed = 0
    
    for i, (test_input, expected) in enumerate(zip(test_cases, expected_results)):
        result = _as_dict(test_input)
        actual = result is not None
        
        status = "PASS" if actual == expected else "FAIL"
        if actual == expected:
            passed += 1
        
        print(f"Test {i+1}: {status} (expected: {expected}, got: {actual})")
        if actual != expected:
            print(f"  Input: {repr(test_input)[:100]}...")
            print(f"  Result: {result}")
    
    print(f"\nFunctional tests: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)

if __name__ == "__main__":
    print("DoS Protection Fix Verification Test")
    print("=" * 50)
    
    # Test size limits
    size_test_passed = test_size_limits()
    
    # Test normal functionality
    functional_test_passed = test_functional_behavior()
    
    print("\n" + "=" * 50)
    print("FIX VERIFICATION RESULTS:")
    print(f"Size limit protection: {'WORKING' if size_test_passed else 'FAILED'}")
    print(f"Normal functionality: {'WORKING' if functional_test_passed else 'FAILED'}")
    
    if size_test_passed and functional_test_passed:
        print("\nSUCCESS: All DoS protections are working correctly!")
        print("✓ Size limits prevent DoS attacks")
        print("✓ Normal functionality preserved")
        sys.exit(0)
    else:
        print("\nFAILURE: DoS protection fix has issues!")
        sys.exit(1)