#!/usr/bin/env python3
"""
Performance test to demonstrate the current loop detection performance issues.
"""

import time
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from loop_detection.detector import LoopDetector, LoopDetectionConfig

def test_current_performance():
    """Test current implementation performance with various scenarios."""
    
    # Create detector with default config
    config = LoopDetectionConfig(
        enabled=True,
        buffer_size=16384,
        max_pattern_length=8192,
        analysis_interval=0  # Disable interval optimization to see worst case
    )
    detector = LoopDetector(config)
    
    # Test 1: Small chunks (simulating token-by-token streaming)
    print("Test 1: Small chunks (token-by-token streaming)")
    start_time = time.time()
    
    # Simulate 1000 small chunks
    for i in range(1000):
        chunk = f"token_{i} "
        detector.process_chunk(chunk)
    
    end_time = time.time()
    print(f"Time for 1000 small chunks: {end_time - start_time:.4f} seconds")
    
    # Test 2: Medium chunks with repetitive content
    print("\nTest 2: Medium chunks with repetitive content")
    detector.reset()
    start_time = time.time()
    
    # Create repetitive content that should trigger detection
    repetitive_chunk = "This is a repetitive sentence that will be repeated many times. " * 2
    
    for i in range(100):
        detector.process_chunk(repetitive_chunk)
    
    end_time = time.time()
    print(f"Time for 100 medium repetitive chunks: {end_time - start_time:.4f} seconds")
    
    # Test 3: Large buffer with complex analysis
    print("\nTest 3: Large buffer analysis")
    detector.reset()
    start_time = time.time()
    
    # Fill buffer with varied content first
    for i in range(50):
        chunk = f"This is unique content number {i}. " * 10
        detector.process_chunk(chunk)
    
    # Then add repetitive content
    repetitive_chunk = "ERROR: Something went wrong. Please try again. " * 3
    for i in range(20):
        detector.process_chunk(repetitive_chunk)
    
    end_time = time.time()
    print(f"Time for large buffer analysis: {end_time - start_time:.4f} seconds")
    
    # Test 4: Worst case - many different pattern lengths
    print("\nTest 4: Worst case - scanning many pattern lengths")
    detector.reset()
    start_time = time.time()
    
    # Create content that will force scanning many different pattern lengths
    base_content = "A" * 200  # Long enough to trigger multiple length checks
    for i in range(50):
        detector.process_chunk(base_content)
    
    end_time = time.time()
    print(f"Time for worst case pattern scanning: {end_time - start_time:.4f} seconds")

if __name__ == "__main__":
    test_current_performance()