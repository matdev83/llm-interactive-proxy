"""Regression test for PathValidationService cache memory leak fix.

This test verifies that PathValidationService properly limits cache size
to prevent unbounded memory growth when many unique paths are normalized.

Fixed: Cache size is limited by cache_max_size parameter, preventing unbounded growth.
"""

import contextlib
import gc
import tracemalloc

import pytest
from src.core.services.path_validation_service import PathValidationService


class TestPathValidationServiceCacheRegression:
    """Regression tests for PathValidationService cache memory leak fix."""

    @pytest.fixture
    def service(self) -> PathValidationService:
        """Create PathValidationService with small cache for testing."""
        return PathValidationService(cache_max_size=100)

    def test_cache_size_limited(self, service: PathValidationService) -> None:
        """Test that cache size does not exceed cache_max_size limit."""
        # Generate many unique paths to exceed cache limit
        for i in range(200):  # Reduced from 1000 for performance
            unique_path = f"/tmp/unique_dir_{i}/file_{i}.txt"
            with contextlib.suppress(ValueError, OSError):
                service.normalize_path(unique_path)

            # Check cache size periodically
            if i % 50 == 0:  # Reduced frequency from 100 for performance
                cache_size = len(service._normalization_cache)
                assert cache_size <= service._cache_max_size, (
                    f"Cache size ({cache_size}) exceeded limit "
                    f"({service._cache_max_size}) at iteration {i}"
                )

        # Final check
        final_cache_size = len(service._normalization_cache)
        assert final_cache_size <= service._cache_max_size, (
            f"Final cache size ({final_cache_size}) exceeded limit "
            f"({service._cache_max_size}). Cache should be limited."
        )

    def test_cache_stops_growing_at_limit(self, service: PathValidationService) -> None:
        """Test that cache stops growing once limit is reached."""
        cache_max_size = service._cache_max_size

        # Add paths until cache is full
        i = 0
        while (
            len(service._normalization_cache) < cache_max_size
            and i < cache_max_size * 2
        ):
            unique_path = f"/tmp/test_dir_{i}/file_{i}.txt"
            with contextlib.suppress(ValueError, OSError):
                service.normalize_path(unique_path)
            i += 1

        # Cache should be at or near limit
        cache_size_after_fill = len(service._normalization_cache)
        assert (
            cache_size_after_fill <= cache_max_size
        ), f"Cache size ({cache_size_after_fill}) exceeded limit ({cache_max_size})"

        # Add more paths - cache should not grow beyond limit
        len(service._normalization_cache)
        for j in range(200):  # Reduced from 500 for performance
            unique_path = f"/tmp/overflow_dir_{j}/file_{j}.txt"
            with contextlib.suppress(ValueError, OSError):
                service.normalize_path(unique_path)

        final_size = len(service._normalization_cache)
        assert final_size <= cache_max_size, (
            f"Cache grew beyond limit: {final_size} > {cache_max_size} "
            "after adding more paths"
        )

    def test_cache_memory_growth_bounded(self) -> None:
        """Test that memory growth is bounded when cache limit is enforced."""
        tracemalloc.start()

        service = PathValidationService(cache_max_size=100)

        # Initial memory measurement
        gc.collect()
        initial_memory, _ = tracemalloc.get_traced_memory()

        # Generate unique paths - minimal iterations to exceed cache limit
        for i in range(
            105
        ):  # Enough to exceed cache limit (100) and verify bounded growth
            unique_path = f"/tmp/memory_test_{i}/file_{i}.txt"
            with contextlib.suppress(ValueError, OSError):
                service.normalize_path(unique_path)

        # Force garbage collection
        gc.collect()

        # Check final state
        current_memory, peak_memory = tracemalloc.get_traced_memory()
        final_cache_size = len(service._normalization_cache)

        tracemalloc.stop()

        # Cache should be limited
        assert final_cache_size <= service._cache_max_size, (
            f"Cache size ({final_cache_size}) exceeded limit "
            f"({service._cache_max_size})"
        )

        # Memory growth should be reasonable (cache is limited)
        # Note: This is a sanity check, exact memory values depend on system
        memory_growth = current_memory - initial_memory
        # Should be less than 1MB for 100 cached paths
        assert memory_growth < 1024 * 1024, (
            f"Memory growth ({memory_growth / 1024:.2f} KB) seems excessive "
            "for limited cache"
        )
