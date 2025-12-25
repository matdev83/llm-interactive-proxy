#!/usr/bin/env python3
"""
Enhanced DoS vulnerability test for hybrid_detector.py

This script specifically targets the worst-case computational complexity 
in the RollingHashTracker._check_pattern_length method.

The vulnerability is triggered when:
1. Content is long enough to trigger pattern checking
2. Content has enough repetition to avoid early termination
3. But content is designed to maximize hash collision checks
"""

import os
import sys
import time

# Add src to path to import module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.loop_detection.hybrid_detector import RollingHashTracker


def create_worst_case_content():
    """Create content that triggers worst-case behavior in rolling hash algorithm."""
    
    # Worst case: content with many similar substrings that create many hash collisions
    # We use a pattern that has many overlapping substrings with same hash
    base = "A" * 50 + "B" * 10 + "A" * 40  # Pattern with overlapping A's
    repetitions = 30
    content = base * repetitions
    return content

def create_high_collision_content():
    """Create content designed to cause hash collisions."""
    
    # Use characters that will likely produce similar hash values
    # when rolling through different positions
    content = ""
    for i in range(100):
        content += "A" * 20 + "B" * 5  # Creates many rolling hash combinations
    return content

def create_boundary_content():
    """Create content that sits right at detection boundaries."""
    
    # Content that's just long enough to trigger processing
    # but structured to avoid early pattern detection
    chars = []
    for i in range(600):  # 600 chars - above 60*3=180 threshold
        chars.append(chr(65 + (i % 4)))  # A, B, C, D repeating
    return "".join(chars)

def test_detailed_performance():
    """Test performance with detailed timing analysis."""
    
    tracker = RollingHashTracker(
        min_pattern_length=60,
        max_pattern_length=500,
        min_repetitions=3,
        max_history=5000  # Increase to allow longer content
    )
    
    test_cases = [
        ("Worst case overlapping", create_worst_case_content()),
        ("High collision content", create_high_collision_content()),
        ("Boundary case content", create_boundary_content()),
        ("Large unique content", "".join(chr(65 + (i % 26)) for i in range(1000))),
        ("Maximum pattern length test", "X" * 499 + "Y" * 499 + "Z" * 499),
    ]
    
    print("Detailed Performance Analysis:")
    print("=" * 60)
    
    total_processing_time = 0
    max_single_time = 0
    
    for name, content in test_cases:
        print(f"\nTest: {name}")
        print(f"Content length: {len(content)}")
        
        tracker.reset()
        
        # Multiple runs to get average
        times = []
        for run in range(3):
            start = time.time()
            try:
                result = tracker.add_content(content)
                end = time.time()
                times.append(end - start)
            except Exception as e:
                print(f"  ERROR: {e}")
                times.append(float('inf'))
                break
        
        if times and times[0] != float('inf'):
            avg_time = sum(times) / len(times)
            min_time = min(times)
            max_time = max(times)
            
            print(f"  Average time: {avg_time:.4f}s")
            print(f"  Min time: {min_time:.4f}s") 
            print(f"  Max time: {max_time:.4f}s")
            result = tracker.add_content(content[:50]) if len(content) > 50 else tracker.add_content(content)
            print(f"  Result: {result}")
            
            total_processing_time += avg_time
            max_single_time = max(max_single_time, avg_time)
            
            # Check if this indicates vulnerability
            if avg_time > 0.5:
                print("  WARNING: Slow processing detected!")
    
    print("\n" + "=" * 60)
    print(f"Total processing time: {total_processing_time:.4f}s")
    print(f"Slowest single test: {max_single_time:.4f}s")
    
    # Vulnerability assessment
    if max_single_time > 1.0:
        print("ALERT: DoS VULNERABILITY CONFIRMED!")
        print("Processing time exceeds acceptable limits")
        return True
    elif total_processing_time > 3.0:
        print("WARNING: Potential DoS vulnerability")
        print("Cumulative processing time is high")
        return True
    else:
        print("OK: Processing times within acceptable limits")
        return False

def test_memory_usage():
    """Test if algorithm can cause excessive memory usage."""
    
    print("\nMemory Usage Test:")
    print("=" * 40)
    
    # Test with progressively larger content
    sizes = [1000, 2000, 5000, 10000]
    
    for size in sizes:
        tracker = RollingHashTracker(max_history=15000)  # Allow larger content
        
        # Create repetitive content that could cause memory growth
        content = "A" * 100 + "B" * 50 + "C" * 25
        content = content * (size // len(content) + 1)
        content = content[:size]
        
        print(f"\nSize: {size} characters")
        
        start = time.time()
        try:
            result = tracker.add_content(content)
            end = time.time()
            
            print(f"Time: {end - start:.4f}s")
            print(f"Content buffer size: {len(tracker.content)}")
            print(f"Pattern candidates: {len(tracker.pattern_candidates)}")
            
            # Check if memory growth is excessive
            if len(tracker.content) > tracker.max_history:
                print("WARNING: Content buffer exceeds max_history!")
            
        except Exception as e:
            print(f"ERROR: {e}")
            if "Memory" in str(e) or "memory" in str(e):
                print("ALERT: Memory-related error - DoS vulnerability!")
                return True
    
    return False

if __name__ == "__main__":
    print("Enhanced DoS Vulnerability Test - Hybrid Detector")
    print("=" * 60)
    
    # Run detailed performance test
    perf_vulnerable = test_detailed_performance()
    
    # Run memory usage test
    mem_vulnerable = test_memory_usage()
    
    print("\n" + "=" * 60)
    print("FINAL ASSESSMENT:")
    print(f"Performance vulnerability: {'YES' if perf_vulnerable else 'NO'}")
    print(f"Memory vulnerability: {'YES' if mem_vulnerable else 'NO'}")
    
    if perf_vulnerable or mem_vulnerable:
        print("\nALERT: DOS VULNERABILITY CONFIRMED!")
        print("The RollingHashTracker has DoS vulnerabilities")
        sys.exit(1)
    else:
        print("\nOK: No significant DoS vulnerabilities detected")
        sys.exit(0)