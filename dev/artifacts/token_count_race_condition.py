"""Reproduction script for race condition in token_count.py

This script demonstrates the race condition in the _tiktoken_encoding
lazy initialization where multiple threads can simultaneously:
1. Check if _tiktoken_encoding is None
2. All call tiktoken.get_encoding() at the same time
3. Race to write to _tiktoken_encoding

While the final state is correct, multiple threads perform redundant
expensive initialization.
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

# Track initialization calls
initialization_count = 0
initialization_lock = threading.Lock()
initialization_times = []


def reset_token_count_cache():
    """Reset the cached tiktoken encoding for testing."""
    import src.core.utils.token_count as tc

    tc._tiktoken_encoding = None


def count_tokens_worker(text: str, worker_id: int) -> tuple[int, float]:
    """Worker that calls count_tokens and tracks initialization."""
    import src.core.utils.token_count as tc

    global initialization_count
    global initialization_times

    start_time = time.time()
    result = tc.count_tokens(text)
    elapsed = time.time() - start_time

    with initialization_lock:
        initialization_count += 1
        initialization_times.append(elapsed)
        print(
            f"Worker {worker_id}: count_tokens returned {result}, took {elapsed:.4f}s"
        )

    return result, elapsed


def test_race_condition_with_threads():
    """Test race condition using multiple threads."""
    print("\n=== Testing with Threads ===")
    print("Simulating concurrent token counting from multiple threads")

    reset_token_count_cache()

    with initialization_lock:
        global initialization_count
        initialization_count = 0
        initialization_times = []

    # Test text
    test_text = "Hello world" * 100

    # Create multiple threads that all call count_tokens simultaneously
    num_threads = 10
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [
            executor.submit(count_tokens_worker, test_text, i)
            for i in range(num_threads)
        ]

        results = [f.result() for f in futures]

    print(f"\nTotal workers: {num_threads}")
    print(f"Initializations that occurred: {initialization_count}")

    if initialization_count > 1:
        print("❌ RACE CONDITION DETECTED: Multiple initializations occurred!")
        print("   Expected: 1 initialization")
        print(f"   Actual: {initialization_count} initializations")
        print(f"   Wasted initialization calls: {initialization_count - 1}")
        return False
    else:
        print("✓ No race condition detected")
        return True


async def test_race_condition_with_async():
    """Test race condition using async tasks."""
    print("\n=== Testing with Async Tasks ===")
    print("Simulating concurrent token counting from async tasks")

    reset_token_count_cache()

    with initialization_lock:
        global initialization_count
        initialization_count = 0
        initialization_times = []

    # Test text
    test_text = "Hello world" * 100

    # Create multiple async tasks that all call count_tokens simultaneously
    num_tasks = 10

    async def async_worker(text: str, worker_id: int) -> tuple[int, float]:
        # Run count_tokens in a thread pool to avoid blocking event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, count_tokens_worker, text, worker_id)

    results = await asyncio.gather(
        *[async_worker(test_text, i) for i in range(num_tasks)]
    )

    print(f"\nTotal tasks: {num_tasks}")
    print(f"Initializations that occurred: {initialization_count}")

    if initialization_count > 1:
        print("❌ RACE CONDITION DETECTED: Multiple initializations occurred!")
        print("   Expected: 1 initialization")
        print(f"   Actual: {initialization_count} initializations")
        print(f"   Wasted initialization calls: {initialization_count - 1}")
        return False
    else:
        print("✓ No race condition detected")
        return True


def main():
    """Run all race condition tests."""
    print("=" * 70)
    print("Race Condition Test for _tiktoken_encoding Lazy Initialization")
    print("=" * 70)

    # Run thread test
    thread_result = test_race_condition_with_threads()

    # Run async test
    async_result = asyncio.run(test_race_condition_with_async())

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    if thread_result and async_result:
        print("✓ All tests passed - No race conditions detected")
        return 0
    else:
        print("❌ Race conditions detected")
        return 1


if __name__ == "__main__":
    exit(main())
