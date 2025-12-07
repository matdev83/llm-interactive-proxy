"""
Production Concurrency Guard - Phase 4 Production Hardening

This module provides production-grade concurrency safeguards for critical operations:
- Monitored async locks with deadlock detection
- Automatic retry with exponential backoff
- Circuit breakers for failing operations
- Comprehensive metrics collection
- Performance monitoring and alerting
"""

import asyncio
import functools
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar, cast
from weakref import WeakSet

logger = logging.getLogger(__name__)
T = TypeVar("T")


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

            # Alert on high contention
            if wait_time > 1.0:  # 1 second wait
                logger.warning(
                    f"High lock contention detected in {lock_name}: {wait_time:.3f}s wait time"
                )

    def record_deadlock_detection(self, lock_name: str) -> None:
        """Record deadlock detection event."""
        with self._metrics_lock:
            self.deadlock_detection_count += 1
            logger.error(f"Deadlock detected and recovered in {lock_name}")

    def record_race_condition_warning(self, operation: str) -> None:
        """Record potential race condition warning."""
        with self._metrics_lock:
            self.race_condition_warnings += 1
            logger.warning(f"Potential race condition in operation: {operation}")

    def record_retry_attempt(self, operation: str, attempt: int) -> None:
        """Record retry attempt."""
        with self._metrics_lock:
            self.retry_attempts += 1
            logger.info(f"Retry attempt {attempt} for operation: {operation}")


# Global metrics instance
production_metrics = ConcurrencyMetrics()


class CircuitBreakerState(Enum):
    """Circuit breaker states for concurrent operations."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    success_threshold: int = 3


class CircuitBreaker:
    """Circuit breaker for concurrent operations."""

    def __init__(self, name: str, config: CircuitBreakerConfig):
        self.name = name
        self.config = config
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
        self._lock = threading.Lock()

    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function with circuit breaker protection."""
        with self._lock:
            if self.state == CircuitBreakerState.OPEN:
                if time.time() - self.last_failure_time > self.config.recovery_timeout:
                    self.state = CircuitBreakerState.HALF_OPEN
                    self.success_count = 0
                else:
                    production_metrics.circuit_breaker_trips += 1
                    raise Exception(
                        f"Circuit breaker {self.name} is OPEN - operation rejected"
                    )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """Handle successful operation."""
        with self._lock:
            if self.state == CircuitBreakerState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.config.success_threshold:
                    self.state = CircuitBreakerState.CLOSED
                    self.failure_count = 0
                    logger.info(
                        f"Circuit breaker {self.name} closed - service recovered"
                    )
            elif self.state == CircuitBreakerState.CLOSED:
                self.failure_count = 0

    def _on_failure(self) -> None:
        """Handle failed operation."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.config.failure_threshold:
                self.state = CircuitBreakerState.OPEN
                logger.error(
                    f"Circuit breaker {self.name} opened after {self.failure_count} failures"
                )


class ProductionAsyncLock:
    """AsyncIO lock with production monitoring and deadlock detection."""

    def __init__(self, name: str = "unnamed", timeout: float = 30.0) -> None:
        self.name = name
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self._holder: str | None = None
        self._acquired_at: float | None = None

    async def acquire(self):
        """Acquire lock with monitoring."""
        start_time = time.time()
        task_name = getattr(asyncio.current_task(), "get_name", lambda: "unknown")()

        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=self.timeout)
            wait_time = time.time() - start_time

            self._holder = task_name
            self._acquired_at = time.time()

            production_metrics.record_lock_contention(wait_time, self.name)

            if wait_time > 5.0:  # 5 second threshold
                logger.warning(
                    f"Long lock wait detected for {self.name}: {wait_time:.3f}s"
                )

        except asyncio.TimeoutError:
            production_metrics.record_deadlock_detection(self.name)
            raise Exception(
                f"Potential deadlock detected in lock {self.name} after {self.timeout}s"
            )

    def release(self) -> None:
        """Release lock with monitoring."""
        if self._acquired_at:
            hold_time = time.time() - self._acquired_at
            if hold_time > 10.0:  # 10 second threshold
                logger.warning(
                    f"Long lock hold detected for {self.name}: {hold_time:.3f}s"
                )

        self._holder = None
        self._acquired_at = None
        self._lock.release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()


@dataclass
class RetryConfig:
    """Configuration for retry operations."""

    max_attempts: int = 3
    base_delay: float = 0.1
    max_delay: float = 5.0
    exponential_base: float = 2.0
    jitter: bool = True


def production_retry(config: RetryConfig):
    """Decorator for automatic retry with exponential backoff and monitoring."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    return await cast(Awaitable[T], func(*args, **kwargs))

                except Exception as e:
                    last_exception = e

                    if attempt == config.max_attempts:
                        logger.error(
                            f"All {config.max_attempts} retry attempts failed for {func.__name__}"
                        )
                        raise

                    production_metrics.record_retry_attempt(func.__name__, attempt)

                    # Calculate delay with exponential backoff
                    delay = min(
                        config.base_delay * (config.exponential_base ** (attempt - 1)),
                        config.max_delay,
                    )

                    # Add jitter to prevent thundering herd
                    if config.jitter:
                        import random

                        delay *= 0.5 + random.random() * 0.5

                    logger.info(
                        f"Retrying {func.__name__} in {delay:.3f}s (attempt {attempt}/{config.max_attempts})"
                    )
                    await asyncio.sleep(delay)

            if last_exception is None:
                # This path should not be reachable if max_attempts >= 1
                raise RuntimeError(f"Internal error in retry logic for {func.__name__}")
            raise last_exception

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    return func(*args, **kwargs)

                except Exception as e:
                    last_exception = e

                    if attempt == config.max_attempts:
                        logger.error(
                            f"All {config.max_attempts} retry attempts failed for {func.__name__}"
                        )
                        raise

                    production_metrics.record_retry_attempt(func.__name__, attempt)

                    # Calculate delay with exponential backoff
                    delay = min(
                        config.base_delay * (config.exponential_base ** (attempt - 1)),
                        config.max_delay,
                    )

                    # Add jitter to prevent thundering herd
                    if config.jitter:
                        import random

                        delay *= 0.5 + random.random() * 0.5

                    logger.info(
                        f"Retrying {func.__name__} in {delay:.3f}s (attempt {attempt}/{config.max_attempts})"
                    )
                    time.sleep(delay)

            if last_exception is None:
                # This path should not be reachable if max_attempts >= 1
                raise RuntimeError(f"Internal error in retry logic for {func.__name__}")
            raise last_exception

        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        else:
            return sync_wrapper

    return decorator


class ConcurrencyGuard:
    """Production-grade concurrency guard with monitoring."""

    def __init__(self, max_concurrent: int = 10, name: str = "unnamed") -> None:
        self.max_concurrent = max_concurrent
        self.name = name
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_operations: WeakSet[object] = WeakSet()
        self._total_operations = 0
        self._rejected_operations = 0

    @asynccontextmanager
    async def acquire(self, operation_name: str = "unknown"):
        """Acquire concurrency slot with monitoring."""
        if len(self._active_operations) >= self.max_concurrent:
            self._rejected_operations += 1
            production_metrics.record_race_condition_warning(
                f"{self.name}:{operation_name}"
            )
            raise Exception(f"Concurrency limit reached for {self.name}")

        async with self._semaphore:
            operation_id = f"{operation_name}_{time.time()}"
            self._active_operations.add(operation_id)
            self._total_operations += 1

            start_time = time.time()
            try:
                yield
            finally:
                duration = time.time() - start_time
                if duration > 30.0:  # 30 second threshold
                    logger.warning(
                        f"Long operation in {self.name}: {operation_name} took {duration:.3f}s"
                    )

                self._active_operations.discard(operation_id)


def get_production_metrics() -> dict[str, Any]:
    """Get comprehensive production metrics."""
    with production_metrics._metrics_lock:
        avg_wait_time = (
            sum(production_metrics.lock_wait_times)
            / len(production_metrics.lock_wait_times)
            if production_metrics.lock_wait_times
            else 0
        )
        max_wait_time = (
            max(production_metrics.lock_wait_times)
            if production_metrics.lock_wait_times
            else 0
        )

        return {
            "lock_contention_count": production_metrics.lock_contention_count,
            "deadlock_detection_count": production_metrics.deadlock_detection_count,
            "race_condition_warnings": production_metrics.race_condition_warnings,
            "retry_attempts": production_metrics.retry_attempts,
            "circuit_breaker_trips": production_metrics.circuit_breaker_trips,
            "avg_lock_wait_time": avg_wait_time,
            "max_lock_wait_time": max_wait_time,
            "total_lock_operations": len(production_metrics.lock_wait_times),
        }
