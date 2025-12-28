"""Test CommandParser pattern cache thread safety."""

import concurrent.futures
import threading

from src.core.commands.parser import CommandParser


def test_pattern_cache_thread_safety() -> None:
    """Test that concurrent pattern compilations don't corrupt the cache."""
    parser = CommandParser()

    # Function that compiles patterns concurrently
    def compile_patterns(prefix: str, iterations: int = 10) -> None:
        for _ in range(iterations):
            # Each thread changes prefix and compiles pattern
            original_prefix = parser.command_prefix
            try:
                parser.command_prefix = prefix
                # Force recompilation by accessing internal _compile_pattern
                _ = parser._compile_pattern()
            finally:
                # Restore original prefix
                parser.command_prefix = original_prefix

    # Use multiple threads to simulate concurrent access
    prefixes = ["/", "!/", "##", "@@", "$$$", "%%%", ">>>", "<<<", "^^^"]
    threads = []

    # Launch 8 concurrent threads with different prefixes
    for prefix in prefixes:
        t = threading.Thread(target=compile_patterns, args=(prefix, 10))
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Verify cache is consistent (no duplicates, no corrupted entries)
    # Access cache under lock to avoid race in test itself
    with CommandParser._cache_lock:
        cache = CommandParser._pattern_cache.copy()

    # All cache entries should be valid compiled patterns
    for _key, pattern in cache.items():
        assert hasattr(pattern, "match"), "Cache entry is not a compiled pattern"
        assert pattern.pattern is not None, "Pattern is None"

    # Cache size should be bounded (not exceed limit significantly)
    assert len(cache) <= 150, f"Cache grew too large: {len(cache)} entries"

    # Reset cache for other tests
    with CommandParser._cache_lock:
        CommandParser._pattern_cache.clear()


def test_concurrent_cache_eviction() -> None:
    """Test that cache eviction works correctly under concurrent load."""
    parser = CommandParser()

    # Fill cache with many different prefixes
    def fill_cache(start_idx: int, count: int) -> None:
        for i in range(start_idx, start_idx + count):
            prefix = f"#{i}#"
            parser.command_prefix = prefix
            _ = parser._compile_pattern()

    # Use thread pool to fill cache concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = []
        for i in range(0, 400, 100):
            future = executor.submit(fill_cache, i, 100)
            futures.append(future)

        # Wait for all to complete
        concurrent.futures.wait(futures)

    # Verify cache size is bounded
    with CommandParser._cache_lock:
        cache_size = len(CommandParser._pattern_cache)

    # Cache should be close to limit (100), not exceed by much due to races
    # Allow some fudge factor for concurrent evictions
    assert cache_size <= 150, f"Cache exceeded limit: {cache_size}"

    # All cached patterns should still work
    parser.command_prefix = "#50#"
    pattern = parser._compile_pattern()
    assert pattern.match("#50#test")

    # Reset cache
    with CommandParser._cache_lock:
        CommandParser._pattern_cache.clear()


def test_no_dict_modification_during_iteration() -> None:
    """Test that cache access doesn't raise RuntimeError due to concurrent modification."""
    parser = CommandParser()

    errors = []
    stop_event = threading.Event()

    def reader() -> None:
        """Continuously read from cache."""
        while not stop_event.is_set():
            try:
                with CommandParser._cache_lock:
                    # Iterate over cache (this would crash if unprotected)
                    for _key, pattern in list(CommandParser._pattern_cache.items()):
                        _ = pattern.pattern
            except RuntimeError as e:
                errors.append(f"Reader error: {e}")
                break

    def writer() -> None:
        """Continuously modify cache."""
        for i in range(200):
            prefix = f"!{i}!"
            parser.command_prefix = prefix
            _ = parser._compile_pattern()

    # Start reader thread
    reader_thread = threading.Thread(target=reader)
    reader_thread.start()

    # Run writer in main thread
    writer()

    # Stop reader
    stop_event.set()
    reader_thread.join()

    # Verify no RuntimeError occurred
    assert len(errors) == 0, f"Errors during concurrent access: {errors}"

    # Reset cache
    with CommandParser._cache_lock:
        CommandParser._pattern_cache.clear()
