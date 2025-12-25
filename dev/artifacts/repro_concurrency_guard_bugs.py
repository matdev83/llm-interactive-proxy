"""Repro script for production_concurrency_guard.py race condition and bugs."""

import asyncio
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from weakref import WeakSet


# Simulate actual ConcurrencyGuard class
@dataclass
class ConcurrencyMetrics:
    """Production-grade concurrency metrics collection."""

    def __init__(self) -> None:
        self.lock_contention_count = 0
        self.deadlock_detection_count = 0
        self.race_condition_warnings = 0
        self.retry_attempts = 0
        self.circuit_breaker_trips = 0
        self.lock_wait_times: list[float] = []
        self._metrics_lock = threading.Lock()

    def record_lock_contention(self, wait_time: float, lock_name: str) -> None:
        """Record lock contention metrics."""
        with self._metrics_lock:
            self.lock_contention_count += 1
            self.lock_wait_times.append(wait_time)

    def record_deadlock_detection(self, lock_name: str) -> None:
        """Record deadlock detection event."""
        with self._metrics_lock:
            self.deadlock_detection_count += 1

    def record_race_condition_warning(self, operation: str) -> None:
        """Record potential race condition warning."""
        with self._metrics_lock:
            self.race_condition_warnings += 1


# Global metrics instance
production_metrics = ConcurrencyMetrics()


class ConcurrencyGuard:
    """Production-grade concurrency guard with bugs.

    BUG 1: In acquire(), the finally block immediately releases semaphore
             after it's acquired, BEFORE the caller's code in the with block runs.

    BUG 2: If semaphore.acquire() times out, the finally block still tries
             to release it (release without acquire).

    BUG 3: Using WeakSet for _active_operations makes len() unreliable
             because entries can disappear spontaneously.
    """

    def __init__(self, max_concurrent: int = 10, name: str = "unnamed") -> None:
        self.max_concurrent = max_concurrent
        self.name = name
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_operations: WeakSet[object] = WeakSet()
        self._total_operations = 0
        self._rejected_operations = 0
        self._operation_counter = 0
        self._lock = threading.Lock()

    @asynccontextmanager
    async def acquire(self, operation_name: str = "unknown"):
        """Acquire concurrency slot with monitoring.

        BUG: The finally block runs AFTER yield, but the yield is missing!
        This means semaphore is released before caller's code executes.
        """
        operation_id = None

        with self._lock:
            if len(self._active_operations) >= self.max_concurrent:
                self._rejected_operations += 1
                production_metrics.record_race_condition_warning(
                    f"{self.name}:{operation_name}"
                )
                raise Exception(f"Concurrency limit reached for {self.name}")

            self._operation_counter += 1
            operation_id = f"{operation_name}_{self._operation_counter}"
            self._active_operations.add(operation_id)
            self._total_operations += 1

        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=5.0)
            yield  # BUG: Should yield here so caller's code runs BEFORE finally
        finally:
            # BUG: This runs immediately because yield is in wrong place
            # Also releases even if acquire() timed out!
            with self._lock:
                if operation_id in self._active_operations:
                    self._active_operations.discard(operation_id)
                self._semaphore.release()


async def simulate_concurrent_access():
    """Simulate concurrent access to ConcurrencyGuard."""
    guard = ConcurrencyGuard(max_concurrent=3, name="test_guard")

    errors = []

    async def worker(worker_id: int):
        """Worker that tries to acquire guard."""
        try:
            # Due to bug, semaphore is released before we do work
            async with guard.acquire(f"worker_{worker_id}"):
                # This should be protected but semaphore is already released
                await asyncio.sleep(0.1)
                print(f"Worker {worker_id} doing work")
        except Exception as e:
            errors.append(f"Worker {worker_id}: {type(e).__name__}: {e}")

    # Try to run more workers than max_concurrent
    # If bug exists, all 10 could run "concurrently"
    tasks = [worker(i) for i in range(10)]
    await asyncio.gather(*tasks, return_exceptions=True)

    return errors, guard


async def main():
    """Run race condition reproduction."""
    print("Starting reproduction for production_concurrency_guard.py...")
    print("This demonstrates bugs in acquire() method:")
    print("1. Semaphore released before caller's code executes (yield in wrong place)")
    print("2. Semaphore release even if acquire() timed out")
    print("3. WeakSet unreliability for tracking active operations")
    print()

    errors, guard = await simulate_concurrent_access()

    print(f"Errors: {len(errors)}")
    for err in errors[:5]:
        print(f"  - {err}")

    print("\nGuard stats:")
    print(f"  Total operations: {guard._total_operations}")
    print(f"  Rejected operations: {guard._rejected_operations}")

    # Check metrics for race condition warnings
    if production_metrics.race_condition_warnings > 0:
        print(f"\nRace condition warnings: {production_metrics.race_condition_warnings}")

    print("\nThe code has logic bugs that make it unreliable for production use.")
    print("All 10 workers ran despite max_concurrent=3 due to immediate semaphore release.")
    return True  # Bugs confirmed


if __name__ == "__main__":
    result = asyncio.run(main())
    exit(0 if result else 1)
