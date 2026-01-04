#!/usr/bin/env python3
"""
Reproduction script for potential memory leak in TestRunnerRegistry.

This script tests whether the TestRunnerRegistry accumulates patterns without bounds.
"""

import gc
import sys
import tracemalloc
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(src_path))

import re

from src.services.test_execution_reminder.test_runner_registry import (
    TestRunnerPattern,
    TestRunnerRegistry,
)


def test_memory_growth():
    """Test if TestRunnerRegistry shows unbounded memory growth."""

    # Start memory tracking
    tracemalloc.start()

    print("Creating TestRunnerRegistry...")
    registry = TestRunnerRegistry()

    # Get initial memory
    snapshot1 = tracemalloc.take_snapshot()
    initial_size = len(registry._patterns)
    print(f"Initial patterns count: {initial_size}")

    # Add many custom patterns (simulating dynamic registration)
    print("Adding 10,000 custom patterns...")
    for i in range(10000):
        pattern = TestRunnerPattern(
            language=f"test_lang_{i}",
            framework=f"test_framework_{i}",
            patterns=[re.compile(f"^test_command_{i}\\b")],
            priority=1,
        )
        registry.register_pattern(pattern)

        if i % 1000 == 0:
            print(f"Added {i} patterns...")

    # Get final memory
    snapshot2 = tracemalloc.take_snapshot()
    final_size = len(registry._patterns)
    print(f"Final patterns count: {final_size}")

    # Compare memory
    top_stats = snapshot2.compare_to(snapshot1, "lineno")
    print("\nTop 10 memory differences:")
    for stat in top_stats[:10]:
        print(stat)

    # Force garbage collection
    gc.collect()

    # Check if patterns persist (they should)
    print(f"\nPatterns after GC: {len(registry._patterns)}")

    # Test with multiple registry instances
    print("\nTesting multiple registry instances...")
    registries = []
    for i in range(100):
        reg = TestRunnerRegistry()
        registries.append(reg)

    total_patterns = sum(len(reg._patterns) for reg in registries)
    print(f"Total patterns across {len(registries)} registries: {total_patterns}")
    print(f"Average patterns per registry: {total_patterns / len(registries):.1f}")

    tracemalloc.stop()

    # Check for memory leak indicators
    if final_size >= initial_size + 10000:  # We added 10k patterns
        print(
            f"\n[LEAK] POTENTIAL MEMORY LEAK: Patterns grew from {initial_size} to {final_size}"
        )
        print("The registry accumulates patterns without any cleanup mechanism.")
        return True
    else:
        print("\n[OK] No obvious memory leak detected")
        return False


if __name__ == "__main__":
    is_leak = test_memory_growth()
    sys.exit(1 if is_leak else 0)
