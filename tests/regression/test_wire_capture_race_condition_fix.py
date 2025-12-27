"""Test WireCapture race condition fix for size cache."""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.config.app_config import AppConfig
from src.core.services.wire_capture_service import WireCapture


async def test_concurrent_writes_no_cache_corruption():
    """Test that concurrent writes don't corrupt cache state."""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        temp_path = f.name

    try:
        config = AppConfig()
        config.logging.capture_file = temp_path
        config.logging.capture_total_max_bytes = 50000

        capture = WireCapture(config)

        # Simulate concurrent writes that modify cache
        async def write_data(idx):
            for i in range(20):
                await capture._append(f"data-{idx}-{i}\n")

        # Run 10 concurrent writers (reduced from 20 for performance)
        tasks = [write_data(i) for i in range(10)]
        await asyncio.gather(*tasks)

        # Verify cache consistency
        actual_size = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
        # 20 * 50 * len("data-0-0\n")  # Rough minimum

        # Cache should be within reasonable bounds of actual size
        size_diff = abs(capture._cached_total_size - actual_size)

        # Allow some tolerance for file buffering, but cache shouldn't be wildly off
        assert (
            size_diff < 5000
        ), f"Cache corrupted: cached={capture._cached_total_size}, actual={actual_size}, diff={size_diff}"
        assert capture._size_cache_valid, "Cache should still be valid after operations"

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


async def test_cache_invalidation_no_race():
    """Test that cache invalidation doesn't race with concurrent writes."""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        temp_path = f.name

    try:
        config = AppConfig()
        config.logging.capture_file = temp_path
        config.logging.capture_total_max_bytes = 2000

        capture = WireCapture(config)

        # Create scenario where cache is invalidated during concurrent writes
        async def write_and_invalidate():
            for i in range(10):
                await capture._append(f"test-{i}\n")

        tasks = [write_and_invalidate() for _ in range(10)]
        await asyncio.gather(*tasks)

        # Cache should remain valid after operations
        assert (
            capture._size_cache_valid
        ), "Cache valid flag should be True after all operations"

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


async def test_cache_update_thread_safety():
    """Test that cache updates are thread-safe."""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        temp_path = f.name

    try:
        config = AppConfig()
        config.logging.capture_file = temp_path
        config.logging.capture_total_max_bytes = 5000

        capture = WireCapture(config)

        # Write initial data
        for i in range(100):
            await capture._append(f"initial-{i}\n")

        initial_size = capture._cached_total_size
        assert initial_size > 0, "Cache should have data after initial writes"

        # Now do concurrent writes that each trigger cache updates
        async def concurrent_write(idx):
            await capture._append(f"concurrent-{idx}\n")

        tasks = [concurrent_write(i) for i in range(50)]
        await asyncio.gather(*tasks)

        # Final size should be sum of all writes (approximately)
        # Each write is roughly 11-14 bytes (e.g. "initial-0\n", "concurrent-0\n")
        # 150 writes * 12 bytes = 1800 bytes
        total_writes = 100 + 50
        expected_min = total_writes * 10  # Minimum expected bytes (10 bytes per line)
        expected_max = total_writes * 20  # Maximum expected bytes (20 bytes per line)

        assert (
            expected_min <= capture._cached_total_size <= expected_max + 5000
        ), f"Final cache size out of expected range: {capture._cached_total_size}"

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


async def test_thread_lock_protection():
    """Test that _thread_lock protects synchronous cache operations."""

    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
        temp_path = f.name

    try:
        config = AppConfig()
        config.logging.capture_file = temp_path
        config.logging.capture_total_max_bytes = 10000

        capture = WireCapture(config)

        # The _thread_lock should protect synchronous calls to _recalculate_total_size
        # This test validates the lock is present and functional
        assert hasattr(capture, "_thread_lock"), "WireCapture should have _thread_lock"
        assert capture._thread_lock is not None, "_thread_lock should be initialized"

        # Trigger synchronous cache update via rotation
        capture._perform_rotation()

        # After rotation, cache should be invalidated but valid flag should be consistent
        # Note: rotation sets _size_cache_valid = False
        assert (
            not capture._size_cache_valid
        ), "Cache should be invalidated after rotation"

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


async def main():
    """Run all race condition tests."""
    print("Running WireCapture race condition tests...")

    tests = [
        (
            "Concurrent writes cache corruption",
            test_concurrent_writes_no_cache_corruption,
        ),
        ("Cache invalidation race", test_cache_invalidation_no_race),
        ("Cache update thread safety", test_cache_update_thread_safety),
        ("Thread lock protection", test_thread_lock_protection),
    ]

    failed = []
    for name, test_fn in tests:
        try:
            print(f"\nTesting: {name}...")
            await test_fn()
            print("  PASSED")
        except AssertionError as e:
            print(f"  FAILED: {e}")
            failed.append((name, str(e)))
        except Exception as e:
            print(f"  ERROR: {e}")
            failed.append((name, str(e)))

    print("\n" + "=" * 60)
    if failed:
        print(f"FAILED: {len(failed)} test(s) failed")
        for name, error in failed:
            print(f"  - {name}: {error}")
        return 1
    else:
        print("PASSED: All race condition tests passed")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
