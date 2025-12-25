#!/usr/bin/env python3
"""
Targeted DoS attack test for hybrid_detector.py

This script creates the worst possible input for the RollingHashTracker
by specifically targeting the computational complexity hotspots.

The vulnerability exists in the nested loop structure:
1. Outer loop: pattern_length from max to min (~440 iterations)
2. Inner loop: rolling through content (up to 5000+ positions)
3. For each position: hash computation and dictionary operations

Total worst-case operations can reach ~2M+ per content addition
"""

import os
import sys
import time

# Add src to path to import module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.loop_detection.hybrid_detector import RollingHashTracker


def create_extreme_case():
    """Create content that maximizes algorithmic complexity."""
    
    # The worst case is content that:
    # 1. Is long enough to trigger full scanning
    # 2. Has just enough repetition to not be filtered out early
    # 3. Contains many hash collisions to maximize inner loop work
    
    # Create content with carefully designed patterns
    base_size = 120  # Just above 60*3=180/3=60 threshold
    content_parts = []
    
    # Use patterns that create many rolling hash variations
    for i in range(40):  # Create 4800 characters of content
        part = ""
        # Varying patterns to maximize hash distribution
        for j in range(base_size):
            char_idx = (i + j) % 6
            part += chr(65 + char_idx)  # A, B, C, D, E, F
        content_parts.append(part)
    
    return "".join(content_parts)

def test_extreme_case():
    """Test with extreme worst-case input."""
    
    print("Testing extreme DoS case...")
    
    # Create tracker with maximum analysis range
    tracker = RollingHashTracker(
        min_pattern_length=60,
        max_pattern_length=500,
        min_repetitions=3,
        max_history=10000  # Allow large content
    )
    
    # Generate extreme content
    malicious_content = create_extreme_case()
    print(f"Generated content length: {len(malicious_content)}")
    print(f"Pattern analysis range: {tracker.max_pattern_length - tracker.min_pattern_length} pattern lengths")
    
    # The theoretical worst-case operations:
    # (max_pattern_length - min_pattern_length) * len(content)
    # = 440 * 4800 = 2,112,000 rolling hash operations
    theoretical_ops = (tracker.max_pattern_length - tracker.min_pattern_length) * len(malicious_content)
    print(f"Theoretical operations: {theoretical_ops:,}")
    
    # Test processing time
    start_time = time.time()
    
    try:
        result = tracker.add_content(malicious_content)
        end_time = time.time()
        
        processing_time = end_time - start_time
        print(f"Processing time: {processing_time:.4f} seconds")
        print(f"Operations per second: {theoretical_ops / processing_time:,.0f}")
        print(f"Result: {result}")
        
        # If it takes more than 0.5 seconds for this operation, it's vulnerable
        if processing_time > 0.5:
            print("\nALERT: DoS VULNERABILITY CONFIRMED!")
            print("Processing time exceeds acceptable threshold")
            print("An attacker could exploit this for CPU exhaustion")
            return True
        else:
            print("\nOK: Processing time within acceptable limits")
            return False
            
    except Exception as e:
        print(f"ERROR during processing: {e}")
        print("This could also be exploited for DoS")
        return True

def test_repeated_attacks():
    """Test repeated content additions to simulate sustained attack."""
    
    print("\nTesting repeated attacks...")
    
    tracker = RollingHashTracker(
        max_pattern_length=500,
        max_history=15000
    )
    
    # Create content that requires processing each time
    attack_content = create_extreme_case()[:3000]  # 3000 chars
    
    print(f"Attack content length: {len(attack_content)}")
    
    # Simulate rapid content additions (like streaming response chunks)
    num_attacks = 5
    total_time = 0
    max_single_time = 0
    
    for i in range(num_attacks):
        start = time.time()
        try:
            # Add some variation to avoid caching optimization
            varied_content = attack_content + str(i)
            result = tracker.add_content(varied_content)
            end = time.time()
            
            attack_time = end - start
            total_time += attack_time
            max_single_time = max(max_single_time, attack_time)
            
            print(f"Attack {i+1}: {attack_time:.4f}s (result: {bool(result)})")
            
        except Exception as e:
            print(f"Attack {i+1}: ERROR - {e}")
            attack_time = float('inf')
            total_time += attack_time
            max_single_time = max(max_single_time, attack_time)
    
    print(f"\nTotal attack time: {total_time:.4f}s")
    print(f"Average per attack: {total_time/num_attacks:.4f}s")
    print(f"Slowest single attack: {max_single_time:.4f}s")
    
    # Check if sustained attack could cause issues
    if max_single_time > 0.3 or total_time > 2.0:
        print("ALERT: Sustained DoS attack vulnerability!")
        return True
    
    return False

def test_boundary_conditions():
    """Test specific boundary conditions that might trigger worst behavior."""
    
    print("\nTesting boundary conditions...")
    
    boundary_tests = [
        # (content_length, description)
        (179, "Just under 60*3 threshold"),
        (180, "Exactly at 60*3 threshold"),
        (181, "Just above 60*3 threshold"),
        (599, "Just under 500*3 threshold"),
        (600, "At 500*3 threshold"),
        (601, "Just over 500*3 threshold"),
        (1499, "Near max practical content"),
        (1500, "At max practical content"),
    ]
    
    vulnerable_cases = 0
    
    for length, description in boundary_tests:
        tracker = RollingHashTracker(max_pattern_length=500)
        
        # Create content that maximizes processing
        content = "".join(chr(65 + (i % 8)) for i in range(length))
        
        start = time.time()
        try:
            result = tracker.add_content(content)
            end = time.time()
            processing_time = end - start
            
            print(f"{description}: {processing_time:.4f}s")
            
            if processing_time > 0.2:  # 200ms threshold for boundary cases
                print("  WARNING: Slow processing at boundary condition")
                vulnerable_cases += 1
                
        except Exception as e:
            print(f"{description}: ERROR - {e}")
            vulnerable_cases += 1
    
    return vulnerable_cases > 0

if __name__ == "__main__":
    print("Targeted DoS Attack Test - Hybrid Detector")
    print("=" * 60)
    
    # Run extreme case test
    extreme_vulnerable = test_extreme_case()
    
    # Run repeated attacks test
    repeated_vulnerable = test_repeated_attacks()
    
    # Run boundary conditions test
    boundary_vulnerable = test_boundary_conditions()
    
    print("\n" + "=" * 60)
    print("VULNERABILITY ASSESSMENT:")
    print(f"Extreme case: {'VULNERABLE' if extreme_vulnerable else 'OK'}")
    print(f"Repeated attacks: {'VULNERABLE' if repeated_vulnerable else 'OK'}")
    print(f"Boundary conditions: {'VULNERABLE' if boundary_vulnerable else 'OK'}")
    
    if extreme_vulnerable or repeated_vulnerable or boundary_vulnerable:
        print("\nALERT: DoS VULNERABILITY CONFIRMED!")
        print("The RollingHashTracker can be exploited for CPU exhaustion")
        sys.exit(1)
    else:
        print("\nOK: No significant DoS vulnerabilities detected")
        sys.exit(0)