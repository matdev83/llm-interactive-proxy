"""Concurrency tests for thread-safe singleton initialization and cache access."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.core.auth.sso.sso_service import JWKSCache
from src.core.ports.streaming_metrics import (
    get_metrics_instance,
    get_sampler_instance,
)
from src.core.services.usage_calculation_service import (
    get_usage_calculation_service,
)


class TestJWKSCacheConcurrency:
    """Test that JWKSCache is thread-safe."""

    def test_concurrent_get_and_set(self):
        """Test concurrent get and set operations don't cause data corruption."""
        cache = JWKSCache(max_size=100, ttl=60)

        class MockJWKS:
            keys = []

        num_threads = 10
        num_ops_per_thread = 100

        def worker_fn(thread_id: int) -> None:
            for i in range(num_ops_per_thread):
                uri = f"jwks_uri_{thread_id}_{i}"
                if i % 2 == 0:
                    # Set operation
                    cache.set(uri, MockJWKS())
                else:
                    # Get operation
                    result = cache.get(uri)
                    # Should either be None or a MockJWKS instance
                    assert result is None or isinstance(result, MockJWKS)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [
                executor.submit(worker_fn, thread_id)
                for thread_id in range(num_threads)
            ]
            for future in as_completed(futures):
                future.result()

    def test_concurrent_eviction(self):
        """Test concurrent LRU eviction doesn't cause race conditions."""
        cache = JWKSCache(max_size=50, ttl=60)

        class MockJWKS:
            keys = []

        # Fill cache to near capacity
        for i in range(45):
            cache.set(f"jwks_uri_{i}", MockJWKS())

        # Concurrently add entries to trigger eviction
        def add_worker(start_idx: int) -> None:
            for i in range(start_idx, start_idx + 20):
                cache.set(f"jwks_uri_{i}", MockJWKS())

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(add_worker, 45 + i * 5) for i in range(4)]
            for future in as_completed(futures):
                future.result()

        # Cache should not exceed max_size
        assert len(cache._cache) <= cache._max_size

    def test_concurrent_get_expired(self):
        """Test concurrent get operations with expired entries."""
        cache = JWKSCache(max_size=100, ttl=1)

        class MockJWKS:
            keys = []

        # Add entries
        for i in range(10):
            cache.set(f"jwks_uri_{i}", MockJWKS())

        # Wait for entries to expire
        time.sleep(1.1)

        # Concurrently access expired entries
        def worker(thread_id: int) -> list[object | None]:
            results = []
            for i in range(10):
                result = cache.get(f"jwks_uri_{i}")
                results.append(result)
            return results

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(worker, i) for i in range(5)]
            all_results = []
            for future in as_completed(futures):
                all_results.extend(future.result())

        # All results should be None (expired)
        assert all(r is None for r in all_results)


class TestStreamingMetricsSingletonConcurrency:
    """Test that streaming metrics singleton initialization is thread-safe."""

    def test_concurrent_get_metrics_instance(self):
        """Test that concurrent calls return the same instance."""
        # Reset the singleton first
        import src.core.ports.streaming_metrics as metrics_module
        metrics_module._global_metrics_instance = None

        num_threads = 10
        instances = []

        def worker() -> None:
            instance = get_metrics_instance()
            instances.append(instance)

        barrier = threading.Barrier(num_threads)

        def worker_with_barrier() -> None:
            barrier.wait()
            instance = get_metrics_instance()
            instances.append(instance)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_with_barrier) for _ in range(num_threads)]
            for future in as_completed(futures):
                future.result()

        # All instances should be the same
        unique_instances = {id(i) for i in instances}
        assert len(unique_instances) == 1, f"Expected 1 unique instance, got {len(unique_instances)}"

    def test_concurrent_get_sampler_instance(self):
        """Test that concurrent calls return the same instance."""
        # Reset the singleton first
        import src.core.ports.streaming_metrics as metrics_module
        metrics_module._global_sampler_instance = None

        num_threads = 10
        instances = []

        barrier = threading.Barrier(num_threads)

        def worker_with_barrier() -> None:
            barrier.wait()
            instance = get_sampler_instance()
            instances.append(instance)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_with_barrier) for _ in range(num_threads)]
            for future in as_completed(futures):
                future.result()

        # All instances should be the same
        unique_instances = {id(i) for i in instances}
        assert len(unique_instances) == 1, f"Expected 1 unique instance, got {len(unique_instances)}"


class TestUsageCalculationServiceSingletonConcurrency:
    """Test that usage calculation service singleton initialization is thread-safe."""

    def test_concurrent_get_service_instance(self):
        """Test that concurrent calls return the same instance."""
        # Reset the singleton first
        import src.core.services.usage_calculation_service as service_module
        service_module._usage_calculation_service = None

        num_threads = 10
        instances = []

        barrier = threading.Barrier(num_threads)

        def worker_with_barrier() -> None:
            barrier.wait()
            instance = get_usage_calculation_service()
            instances.append(instance)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_with_barrier) for _ in range(num_threads)]
            for future in as_completed(futures):
                future.result()

        # All instances should be the same
        unique_instances = {id(i) for i in instances}
        assert len(unique_instances) == 1, f"Expected 1 unique instance, got {len(unique_instances)}"
