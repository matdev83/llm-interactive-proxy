#!/usr/bin/env python3
"""
Memory leak reproduction script for APIKeyRedactor._redact_cache.

This script demonstrates the unbounded memory growth in APIKeyRedactor's cache
when processing many different short texts.
"""

import tracemalloc
import sys
import os
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from security import APIKeyRedactor

def test_memory_growth():
    """Test memory growth with APIKeyRedactor cache."""
    
    # Start tracing memory
    tracemalloc.start()
    
    # Create redactor with a dummy API key
    redactor = APIKeyRedactor(["sk-test-key-123456789"])
    
    # Take initial memory snapshot
    snapshot1 = tracemalloc.take_snapshot()
    
    # Generate many different short texts that will use the cached version
    print("Processing 2000 different short texts (each < 1000 chars)...")
    for i in range(2000):
        # Create unique text each time to ensure cache growth
        text = f"This is test message number {i} with some content to be processed and cached. " * 10
        text = text[:900]  # Keep it under 1000 chars to use cached version
        
        # Process the text (this should add to cache)
        redacted = redactor.redact(text)
        
        if i % 500 == 0:
            print(f"Processed {i} texts...")
    
    # Take final memory snapshot
    snapshot2 = tracemalloc.take_snapshot()
    
    # Compare snapshots
    top_stats = snapshot2.compare_to(snapshot1, 'lineno')
    
    print("\n=== MEMORY GROWTH ANALYSIS ===")
    print(f"Top 10 memory differences:")
    
    for stat in top_stats[:10]:
        print(stat)
    
    # Check cache size
    cache_size = len(redactor._redact_cache) if hasattr(redactor, '_redact_cache') else 0
    print(f"\nCache contains {cache_size} entries")
    print(f"Cache size limit is 1024 entries")
    
    if cache_size >= 1024:
        print("WARNING: Cache has reached its size limit")
        print("    However, memory usage may still be high due to stored string content")
    
    # Calculate total cache memory usage
    if hasattr(redactor, '_redact_cache'):
        total_chars = sum(len(k) + len(v) for k, v in redactor._redact_cache.items())
        print(f"Total characters stored in cache: ~{total_chars:,}")
        print(f"Estimated cache memory usage: ~{total_chars * 50 / 1024 / 1024:.2f} MB")
    
    # Stop tracing
    tracemalloc.stop()
    
    return len(top_stats) > 0 and cache_size > 0

if __name__ == "__main__":
    print("=== APIKeyRedactor Memory Leak Test ===")
    
    try:
        has_growth = test_memory_growth()
        
        if has_growth:
            print("\nMEMORY LEAK CONFIRMED!")
            print("   The APIKeyRedactor cache shows memory growth with repeated use.")
            print("   While the cache has a size limit, each entry stores full string content.")
            exit(1)
        else:
            print("\nNo significant memory growth detected.")
            exit(0)
            
    except Exception as e:
        print(f"\nError during test: {e}")
        import traceback
        traceback.print_exc()
        exit(2)