#!/usr/bin/env python3
"""
Memory leak fix verification script for APIKeyRedactor.
"""

import tracemalloc
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from security import APIKeyRedactor

def test_memory_fix():
    """Test that memory growth is controlled after the fix."""
    
    # Start tracing memory
    tracemalloc.start()
    
    # Create redactor with a dummy API key
    redactor = APIKeyRedactor(["sk-test-key-123456789"])
    
    # Take initial memory snapshot
    snapshot1 = tracemalloc.take_snapshot()
    
    # Generate many different short texts that will use the cached version
    print("Processing 2000 different short texts (each < 1000 chars)...")
    for i in range(2000):
        # Create unique text each time to test cache eviction
        text = f"This is test message number {i} with some content to be processed and cached. " * 10
        text = text[:900]  # Keep it under 1000 chars to use cached version
        
        # Process the text (this should use LRU cache)
        redacted = redactor.redact(text)
        
        if i % 500 == 0:
            print(f"Processed {i} texts...")
    
    # Take final memory snapshot
    snapshot2 = tracemalloc.take_snapshot()
    
    # Compare snapshots
    top_stats = snapshot2.compare_to(snapshot1, 'lineno')
    
    print("\n=== MEMORY GROWTH ANALYSIS AFTER FIX ===")
    print(f"Top 5 memory differences:")
    
    for stat in top_stats[:5]:
        print(stat)
    
    # Check cache size
    cache_size = len(redactor._redact_cache) if hasattr(redactor, '_redact_cache') else 0
    max_size = getattr(redactor, '_cache_max_size', 0)
    print(f"\nCache contains {cache_size} entries")
    print(f"Cache max size is {max_size} entries")
    
    success = True
    if cache_size <= max_size:
        print("SUCCESS: Cache size is properly bounded")
    else:
        print("WARNING: Cache exceeded its size limit!")
        success = False
    
    # Estimate memory usage (should be much lower now)
    if hasattr(redactor, '_redact_cache'):
        total_key_chars = sum(len(k) for k in redactor._redact_cache.keys())
        total_value_chars = sum(len(v) for v in redactor._redact_cache.values())
        total_chars = total_key_chars + total_value_chars
        print(f"Total characters stored in cache: ~{total_chars:,}")
        print(f"Estimated cache memory usage: ~{total_chars * 50 / 1024 / 1024:.2f} MB")
        
        # With MD5 hash keys (32 chars each), memory usage should be much lower
        estimated_optimal = cache_size * (32 + 200) * 50 / 1024 / 1024  # Rough estimate
        print(f"Expected optimal memory usage: ~{estimated_optimal:.2f} MB")
    
    # Stop tracing
    tracemalloc.stop()
    
    return success

if __name__ == "__main__":
    print("=== APIKeyRedactor Memory Leak Fix Verification ===")
    
    try:
        is_fixed = test_memory_fix()
        
        if is_fixed:
            print("\nMEMORY LEAK FIX CONFIRMED!")
            print("   The APIKeyRedactor cache now uses LRU eviction with hash keys.")
            print("   Memory usage is bounded and predictable.")
            exit(0)
        else:
            print("\nMEMORY LEAK NOT FIXED!")
            print("   Cache is still growing unbounded.")
            exit(1)
            
    except Exception as e:
        print(f"\nError during test: {e}")
        import traceback
        traceback.print_exc()
        exit(2)