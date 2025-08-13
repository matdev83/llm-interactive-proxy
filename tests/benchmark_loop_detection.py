#!/usr/bin/env python3
"""
Benchmark script for loop detection performance improvements.
"""

import os
import sys
import time

# Add current directory to path so we can import the modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.loop_detection.config import LoopDetectionConfig
from src.loop_detection.detector import LoopDetector


def create_test_data(pattern_size=120, repetitions=10):
    """Create test data with repeated patterns."""
    pattern = "ERROR " * (pattern_size // 6)  # Each "ERROR " is 6 chars
    return pattern * repetitions


def benchmark_original_approach():
    """Benchmark the original approach."""
    # Create test data
    test_text = create_test_data(120, 10)
    
    # Configure detector
    config = LoopDetectionConfig(
        enabled=True,
        buffer_size=16384,
        max_pattern_length=8192
    )
    
    detector = LoopDetector(config=config)
    
    # Measure performance
    start_time = time.time()
    result = detector.process_chunk(test_text)
    end_time = time.time()
    
    return end_time - start_time, result is not None


def benchmark_chunk_aggregation():
    """Benchmark chunk aggregation approach."""
    # Create test data as small chunks
    pattern = "ERROR " * 20  # 120 chars
    test_chunks = [pattern] * 10  # 10 chunks
    
    # Configure detector
    config = LoopDetectionConfig(
        enabled=True,
        buffer_size=16384,
        max_pattern_length=8192
    )
    
    detector = LoopDetector(config=config)
    
    # Measure performance with chunk aggregation
    start_time = time.time()
    for chunk in test_chunks:
        result = detector.process_chunk(chunk)
        if result:
            break
    end_time = time.time()
    
    return end_time - start_time


def main():
    """Run benchmarks and report results."""
    print("Loop Detection Performance Benchmark")
    print("=" * 40)
    
    # Test 1: Single large chunk processing
    print("\n1. Single large chunk processing:")
    time_taken, detected = benchmark_original_approach()
    print(f"   Time taken: {time_taken:.6f} seconds")
    print(f"   Loop detected: {detected}")
    
    # Test 2: Chunk aggregation processing
    print("\n2. Chunk aggregation processing:")
    time_taken = benchmark_chunk_aggregation()
    print(f"   Time taken: {time_taken:.6f} seconds")
    
    print("\nBenchmark completed!")


if __name__ == "__main__":
    main()