#!/usr/bin/env python3
"""
DoS vulnerability test for rate_limit.py _as_dict function

This script tests the vulnerability in src/rate_limit.py _as_dict function
where json.loads() is called without size limits on potentially large strings.
"""

import sys
import os
import time
import json

# Add src to path to import module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.rate_limit import _as_dict

def test_large_string_parsing():
    """Test _as_dict with large string input."""
    
    print("Testing _as_dict with large string input...")
    print("=" * 60)
    
    # Create a large string that could cause DoS
    # The _as_dict function will try to extract JSON from this string
    large_string = "Some text before JSON " + "{" + "data: [" + ",".join([f'"item_{i}"' for i in range(100000)]) + "]}" + " Some text after JSON"
    
    print(f"Input string length: {len(large_string):,} characters")
    print(f"Input string size: {len(large_string.encode('utf-8')):,} bytes")
    
    # Test parsing
    start_time = time.time()
    
    try:
        result = _as_dict(large_string)
        end_time = time.time()
        
        print(f"Processing completed in {end_time - start_time:.4f} seconds")
        print(f"Result type: {type(result)}")
        
        if result is not None:
            print(f"Parsed dict keys: {list(result.keys())}")
            if 'data' in result and isinstance(result['data'], list):
                print(f"Array length: {len(result['data']):,}")
        
        # Check if this took too long (indicates vulnerability)
        if end_time - start_time > 1.0:
            print("WARNING: Processing time indicates potential DoS vulnerability!")
            return True
        
        print("OK: Processing completed within acceptable limits")
        return False
        
    except MemoryError:
        end_time = time.time()
        print(f"MEMORY ERROR: Processing caused memory exhaustion!")
        print(f"Error occurred after {end_time - start_time:.4f} seconds")
        return True
        
    except Exception as e:
        end_time = time.time()
        print(f"ERROR: {type(e).__name__}: {e}")
        print(f"Error occurred after {end_time - start_time:.4f} seconds")
        
        # Check if error is resource-related (vulnerability)
        if any(keyword in str(e).lower() for keyword in ["memory", "size", "limit"]):
            print("WARNING: Resource-related error - potential DoS vulnerability!")
            return True
        
        return True  # Any error that could be induced is a vulnerability

def test_nested_json_extraction():
    """Test _as_dict with nested JSON that requires complex parsing."""
    
    print("\nTesting _as_dict with complex nested JSON...")
    print("-" * 40)
    
    # Create deeply nested JSON structure
    def create_nested_data(depth):
        if depth <= 0:
            return {"value": f"deep_value_{depth}", "array": list(range(1000))}
        return {
            f"level_{depth}": create_nested_data(depth - 1),
            "extra_data": list(range(500)),
            "string_data": "X" * 1000
        }
    
    nested_data = create_nested_data(20)  # 20 levels deep
    json_str = json.dumps(nested_data)
    
    # Wrap with text to simulate real-world scenario
    test_string = f"Error prefix {json_str} Error suffix"
    
    print(f"Nested JSON string length: {len(test_string):,} characters")
    
    start_time = time.time()
    
    try:
        result = _as_dict(test_string)
        end_time = time.time()
        
        print(f"Nested JSON parsed in {end_time - start_time:.4f} seconds")
        
        if end_time - start_time > 2.0:
            print("WARNING: Nested JSON parsing took too long!")
            return True
        
        print("OK: Nested JSON parsed within acceptable time")
        return False
        
    except RecursionError:
        end_time = time.time()
        print(f"RECURSION ERROR: Deep nesting caused stack overflow!")
        print(f"Error occurred after {end_time - start_time:.4f} seconds")
        return True
        
    except Exception as e:
        end_time = time.time()
        print(f"ERROR with nested JSON: {type(e).__name__}: {e}")
        
        if "recursion" in str(e).lower():
            return True
        
        return False

def test_massive_array_extraction():
    """Test _as_dict with massive arrays."""
    
    print("\nTesting _as_dict with massive arrays...")
    print("-" * 40)
    
    # Create JSON with massive arrays
    massive_data = {
        "large_array": list(range(500000)),  # 500k elements
        "multiple_arrays": [list(range(10000)) for _ in range(50)],  # 50 arrays of 10k each
        "nested_structure": {
            "level1": {
                "arrays": [list(range(5000)) for _ in range(20)]  # More nested arrays
            }
        }
    }
    
    json_str = json.dumps(massive_data)
    test_string = f"Data: {json_str}"
    
    print(f"Massive array JSON length: {len(test_string):,} characters")
    print(f"Array elements count: {len(massive_data['large_array']):,}")
    
    start_time = time.time()
    
    try:
        result = _as_dict(test_string)
        end_time = time.time()
        
        print(f"Massive array JSON parsed in {end_time - start_time:.4f} seconds")
        
        if result and 'large_array' in result:
            print(f"Parsed array length: {len(result['large_array']):,}")
        
        if end_time - start_time > 3.0:
            print("WARNING: Massive array parsing took too long!")
            return True
        
        print("OK: Massive array JSON parsed within acceptable time")
        return False
        
    except MemoryError:
        end_time = time.time()
        print(f"MEMORY ERROR: Massive array caused memory exhaustion!")
        return True
        
    except Exception as e:
        end_time = time.time()
        print(f"ERROR with massive array: {type(e).__name__}: {e}")
        
        if "memory" in str(e).lower():
            return True
        
        return False

def test_repeated_attacks():
    """Test repeated calls to simulate attack scenario."""
    
    print("\nTesting repeated attacks...")
    print("-" * 40)
    
    # Create moderately sized payload that won't individually trigger alerts
    attack_data = {
        "data": list(range(50000)),  # 50k elements
        "metadata": {"info": "X" * 1000}  # 1KB string
    }
    
    json_str = json.dumps(attack_data)
    test_string = f"Response: {json_str}"
    
    print(f"Attack payload size: {len(test_string):,} characters")
    
    # Test rapid repeated processing
    num_attacks = 100
    total_time = 0
    failures = 0
    
    for i in range(num_attacks):
        start = time.time()
        try:
            result = _as_dict(test_string)
            end = time.time()
            total_time += (end - start)
        except Exception as e:
            failures += 1
            end = time.time()
            total_time += (end - start)
    
    avg_time = total_time / num_attacks
    print(f"Processed {num_attacks} payloads in {total_time:.4f} seconds")
    print(f"Average time per payload: {avg_time:.6f} seconds")
    print(f"Failures: {failures}/{num_attacks}")
    
    if avg_time > 0.01 or failures > 0:
        print("WARNING: Repeated processing shows degradation!")
        return True
    
    return False

if __name__ == "__main__":
    print("DoS Vulnerability Test - rate_limit.py _as_dict function")
    print("=" * 70)
    
    # Run all tests
    test1_vulnerable = test_large_string_parsing()
    test2_vulnerable = test_nested_json_extraction()
    test3_vulnerable = test_massive_array_extraction()
    test4_vulnerable = test_repeated_attacks()
    
    print("\n" + "=" * 70)
    print("VULNERABILITY ASSESSMENT:")
    print(f"Large string parsing: {'VULNERABLE' if test1_vulnerable else 'OK'}")
    print(f"Nested JSON parsing: {'VULNERABLE' if test2_vulnerable else 'OK'}")
    print(f"Massive array parsing: {'VULNERABLE' if test3_vulnerable else 'OK'}")
    print(f"Repeated attacks: {'VULNERABLE' if test4_vulnerable else 'OK'}")
    
    if test1_vulnerable or test2_vulnerable or test3_vulnerable or test4_vulnerable:
        print("\nALERT: DoS VULNERABILITY CONFIRMED!")
        print("The _as_dict function in rate_limit.py is vulnerable to DoS attacks")
        print("through malicious large string inputs requiring JSON parsing")
        sys.exit(1)
    else:
        print("\nOK: No significant DoS vulnerabilities detected")
        sys.exit(0)