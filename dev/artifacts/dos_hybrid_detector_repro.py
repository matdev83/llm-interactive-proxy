#!/usr/bin/env python3
"""
DoS vulnerability reproduction script for hybrid_detector.py

This script demonstrates a potential DoS vulnerability in the RollingHashTracker._check_pattern_length
method where an attacker can craft input that causes excessive CPU usage through nested loops.

The vulnerability exists because:
1. The method iterates through pattern lengths from max to min (lines 104-108)
2. For each pattern length, it rolls through the entire content (lines 131-143)
3. An attacker can craft content that maximizes the number of iterations

Test case: Content with repeated patterns that trigger many pattern length checks
"""

import sys
import os
import time

# Add src to path to import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.loop_detection.hybrid_detector import RollingHashTracker

def test_dos_vulnerability():
    """Test the DoS vulnerability with crafted input."""
    print("Testing DoS vulnerability in RollingHashTracker...")
    
    # Create tracker with default settings
    tracker = RollingHashTracker(
        min_pattern_length=60,  # Default: MIN_LONG_PATTERN_LENGTH
        max_pattern_length=500,  # Default: MAX_LONG_PATTERN_LENGTH
        min_repetitions=3,
        max_history=2000
    )
    
    # Craft malicious content that triggers maximum iterations
    # We create content that will cause the detector to check many pattern lengths
    # and for each pattern length, iterate through the entire content
    
    # Create content that will NOT trigger early detection but still requires full processing
    # We want content that makes the algorithm check all pattern lengths without finding matches early
    # Use content that has no clear repetitions but is at the threshold
    malicious_content = "".join(chr(65 + (i % 26)) for i in range(1800))  # 1800 unique-ish chars
    
    print(f"Content length: {len(malicious_content)}")
    print(f"Pattern length range: {tracker.min_pattern_length} to {tracker.max_pattern_length}")
    print(f"Expected iterations: ~{(tracker.max_pattern_length - tracker.min_pattern_length) * len(malicious_content)}")
    
    # Measure time taken
    start_time = time.time()
    
    try:
        result = tracker.add_content(malicious_content)
        end_time = time.time()
        
        print(f"Processing completed in {end_time - start_time:.4f} seconds")
        print(f"Result: {result}")
        
        # If it takes more than 1 second for a simple operation, it's potentially vulnerable
        if end_time - start_time > 1.0:
            print("WARNING: POTENTIAL DoS VULNERABILITY DETECTED!")
            print("   Processing time exceeds acceptable threshold")
            return True
        else:
            print("OK: Processing time within acceptable limits")
            return False
            
    except Exception as e:
        print(f"ERROR: Error during processing: {e}")
        return True  # Errors that could be induced by malformed input are also vulnerabilities

def test_edge_cases():
    """Test edge cases that could trigger the vulnerability."""
    print("\nTesting edge cases...")
    
    tracker = RollingHashTracker(max_pattern_length=500)
    
    test_cases = [
        # Case 1: Content just at the threshold for triggering detection
        ("A" * 180, "Minimum threshold content"),
        
        # Case 2: Content with many different pattern lengths
        ("A" * 100 + "B" * 100 + "C" * 100 + "D" * 100 + "E" * 100, "Multi-pattern content"),
        
        # Case 3: Content that maximizes pattern length checks
        ("A" * 250 + "B" * 250, "Two long patterns"),
        
        # Case 4: Content with varying character frequencies
        ("A" * 50 + "B" * 50 + "C" * 50 + "D" * 50 + "E" * 50 + "F" * 50 + "G" * 50 + "H" * 50, "8 different chars"),
    ]
    
    vulnerable_cases = 0
    
    for content, description in test_cases:
        print(f"\nTesting: {description}")
        print(f"Content length: {len(content)}")
        
        tracker.reset()  # Reset for each test
        
        start_time = time.time()
        try:
            result = tracker.add_content(content)
            end_time = time.time()
            
            print(f"Time: {end_time - start_time:.4f} seconds")
            print(f"Result: {result}")
            
            if end_time - start_time > 0.5:  # Lower threshold for edge cases
                print("WARNING: Slow processing detected")
                vulnerable_cases += 1
                
        except Exception as e:
            print(f"ERROR: Error: {e}")
            vulnerable_cases += 1
    
    return vulnerable_cases > 0

if __name__ == "__main__":
    print("DoS Vulnerability Test - Hybrid Detector")
    print("=" * 50)
    
    # Run main vulnerability test
    main_test_failed = test_dos_vulnerability()
    
    # Run edge case tests
    edge_cases_failed = test_edge_cases()
    
    print("\n" + "=" * 50)
    print("TEST SUMMARY:")
    print(f"Main test: {'VULNERABLE' if main_test_failed else 'OK'}")
    print(f"Edge cases: {'VULNERABLE' if edge_cases_failed else 'OK'}")
    
    if main_test_failed or edge_cases_failed:
        print("\nALERT: DOS VULNERABILITY CONFIRMED!")
        print("   The RollingHashTracker is vulnerable to DoS attacks")
        sys.exit(1)
    else:
        print("\nOK: No DoS vulnerabilities detected")
        sys.exit(0)