"""Regression tests for race condition fixes in PathValidationService."""

import asyncio
from pathlib import Path

from src.core.services.path_validation_service import PathValidationService


async def test_concurrent_normalize_no_race():
    """Test that concurrent normalize_path calls don't cause race conditions."""
    service = PathValidationService(cache_max_size=100)
    paths = ["/tmp/test", "~/Documents", "../test", "/var/log", "./config"] * 50

    async def normalize_batch(path_list):
        batch_results = []
        for p in path_list:
            result = service.normalize_path(p)
            batch_results.append(result)
        return batch_results

    tasks = [normalize_batch(paths) for _ in range(20)]
    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_flat = []
    for lst in all_results:
        all_flat.extend(lst)
    errors = [r for r in all_flat if isinstance(r, Exception)]
    assert len(errors) == 0, f"Expected no errors, got {len(errors)}"

    results = [r for r in all_flat if isinstance(r, Path)]
    assert (
        len(results) == len(paths) * 20
    ), f"Expected {len(paths) * 20} results, got {len(results)}"


if __name__ == "__main__":
    test_concurrent_normalize_no_race()
    print("PASS: test_concurrent_normalize_no_race")
