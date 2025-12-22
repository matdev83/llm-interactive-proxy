#!/usr/bin/env python3
"""
Simple memory leak test for PathValidationService cache logic.
We'll directly test the problematic code without imports.
"""

import gc
import tracemalloc
from pathlib import Path


class MockPathValidationService:
    """Simplified version of PathValidationService to test cache behavior."""
    
    def __init__(self, cache_max_size: int = 1000):
        self._cache_max_size = cache_max_size
        self._normalization_cache: dict[tuple[str, str | None], Path] = {}
        print(f"Initialized with cache_max_size={cache_max_size}")
    
    def normalize_path_simple(self, path: str, base_dir: str | None = None) -> Path:
        """Simplified normalize that just caches paths without actual normalization."""
        cache_key = (path, base_dir)
        if cache_key in self._normalization_cache:
            return self._normalization_cache[cache_key]
        
        # Simplified "normalization" - just return the path as a Path object
        normalized = Path(path)
        
        # Cache result if we haven't exceeded cache size
        if len(self._normalization_cache) < self._cache_max_size:
            self._normalization_cache[cache_key] = normalized
        
        return normalized


def test_memory_growth():
    """Test for memory leak in cache logic."""
    print("Testing PathValidationService cache logic for memory leaks...")
    
    # Start memory tracing
    tracemalloc.start()
    
    # Create service with small cache
    service = MockPathValidationService(cache_max_size=100)
    
    # Generate requests to exceed cache limit
    initial_memory = 0
    for i in range(1000):
        unique_path = f"/tmp/unique_dir_{i}/file_{i}.txt"
        result = service.normalize_path_simple(unique_path)
        
        if i == 0:
            gc.collect()
            initial_memory, _ = tracemalloc.get_traced_memory()
        
        # Check cache size periodically
        if i % 100 == 0:
            cache_size = len(service._normalization_cache)
            print(f"Iteration {i}: cache_size={cache_size}")
    
    # Force garbage collection
    gc.collect()
    
    # Check final state
    current, peak = tracemalloc.get_traced_memory()
    final_cache_size = len(service._normalization_cache)
    
    print(f"\nResults:")
    print(f"Initial memory: {initial_memory / 1024:.2f} KB")
    print(f"Current memory: {current / 1024:.2f} KB")
    print(f"Peak memory: {peak / 1024:.2f} KB")
    print(f"Memory growth: {(current - initial_memory) / 1024:.2f} KB")
    print(f"Final cache size: {final_cache_size}")
    print(f"Expected cache size: 100")
    
    # Test if cache stops growing at limit (correct behavior)
    if final_cache_size <= 100:
        print("OK Cache properly limited to configured size")
        return False
    else:
        print("MEMORY LEAK: Cache exceeded configured limit!")
        return True


if __name__ == "__main__":
    is_leak = test_memory_growth()
    if is_leak:
        print("\nCONFIRMED: PathValidationService cache logic has a memory leak!")
        exit(1)
    else:
        print("\nNo memory leak detected - cache properly limited.")
        exit(0)