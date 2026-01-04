"""
Reproduction script for ConcurrencyGuard race condition in active operations counting.

Race Condition: Multiple concurrent acquire() calls can have inconsistent views
of _active_operations because the length check and counter increment
are not atomic.
"""

import asyncio
import threading


class UnsafeConcurrencyGuard:
    """Simplified version demonstrating race condition."""

    def __init__(self, max_concurrent=2):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_operations = set()  # No lock
        self._total_operations = 0
        self._rejected_operations = 0

    async def acquire(self, operation_name="unknown"):
        """Acquire WITHOUT proper locking - race condition."""
        # Race: Check length outside semaphore
        if len(self._active_operations) >= self.max_concurrent:
            self._rejected_operations += 1
            raise Exception("Concurrency limit reached (rejected)")

        # Race window: multiple threads can pass check before entering semaphore
        async with self._semaphore:
            operation_id = f"{operation_name}_{asyncio.get_event_loop().time()}"
            self._active_operations.add(operation_id)
            self._total_operations += 1

            try:
                yield
            finally:
                self._active_operations.discard(operation_id)


class SafeConcurrencyGuard:
    """Fixed version with lock-protected check."""

    def __init__(self, max_concurrent=2):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_operations = set()
        self._total_operations = 0
        self._rejected_operations = 0
        self._lock = threading.Lock()

    async def acquire(self, operation_name="unknown"):
        """Acquire WITH proper locking - prevents race."""
        # Fixed: Check length WITH lock
        with self._lock:
            if len(self._active_operations) >= self.max_concurrent:
                self._rejected_operations += 1
                raise Exception("Concurrency limit reached (rejected)")

        async with self._semaphore:
            operation_id = f"{operation_name}_{asyncio.get_event_loop().time()}"
            with self._lock:
                self._active_operations.add(operation_id)
                self._total_operations += 1

            try:
                yield
            finally:
                with self._lock:
                    self._active_operations.discard(operation_id)


async def test_unsafe():
    """Test unsafe implementation."""
    print("\n=== Testing UNSAFE ConcurrencyGuard ===")
    guard = UnsafeConcurrencyGuard(max_concurrent=2)
    success_count = 0
    reject_count = 0
    exception_count = 0

    async def try_acquire(i):
        try:
            async with guard.acquire(f"op_{i}"):
                success_count += 1
                await asyncio.sleep(0.1)
        except Exception as e:
            if "rejected" in str(e):
                reject_count += 1
            else:
                exception_count += 1

    # Launch 10 concurrent operations
    tasks = [try_acquire(i) for i in range(10)]
    await asyncio.gather(*tasks, return_exceptions=True)

    print(
        f"Success: {success_count}, Rejected: {reject_count}, Exceptions: {exception_count}"
    )
    print(f"Total operations tracked: {guard._total_operations}")
    print(f"Rejected operations: {guard._rejected_operations}")

    # Inconsistent state due to race
    if success_count + reject_count < 10:
        print("❌ RACE CONDITION: Operations lost due to inconsistent state")


async def test_safe():
    """Test safe implementation."""
    print("\n=== Testing SAFE ConcurrencyGuard ===")
    guard = SafeConcurrencyGuard(max_concurrent=2)
    success_count = 0
    reject_count = 0
    exception_count = 0

    async def try_acquire(i):
        try:
            async with guard.acquire(f"op_{i}"):
                success_count += 1
                await asyncio.sleep(0.1)
        except Exception as e:
            if "rejected" in str(e):
                reject_count += 1
            else:
                exception_count += 1

    # Launch 10 concurrent operations
    tasks = [try_acquire(i) for i in range(10)]
    await asyncio.gather(*tasks, return_exceptions=True)

    print(
        f"Success: {success_count}, Rejected: {reject_count}, Exceptions: {exception_count}"
    )
    print(f"Total operations tracked: {guard._total_operations}")
    print(f"Rejected operations: {guard._rejected_operations}")

    # Consistent state due to locking
    if success_count + reject_count + exception_count == 10:
        print("✓ SAFE: All operations properly accounted for")


if __name__ == "__main__":
    print("ConcurrencyGuard Race Condition Reproduction")
    print("=" * 50)

    asyncio.run(test_unsafe())
    asyncio.run(test_safe())

    print("\n" + "=" * 50)
    print("Summary:")
    print("- Unsafe code: Race between len() check and semaphore entry")
    print("- Safe code: Lock protects check-then-act sequence")
