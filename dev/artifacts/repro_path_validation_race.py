"""Reproduce race condition in PathValidationService._normalization_cache"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.services.path_validation_service import PathValidationService


async def test_concurrent_normalize():
    """Test concurrent access to normalize_path method to expose race condition."""
    service = PathValidationService(cache_max_size=100)
    paths = ["/tmp/test", "~/Documents", "../test", "/var/log", "./config"] * 20
    results = []
    errors = []

    async def normalize_batch(path_list):
        batch_results = []
        batch_errors = []
        for p in path_list:
            try:
                result = service.normalize_path(p)
                batch_results.append(result)
            except Exception as e:
                batch_errors.append(e)
        return batch_results, batch_errors

    tasks = [normalize_batch(paths) for _ in range(10)]
    all_results = await asyncio.gather(*tasks)

    for batch_results, batch_errors in all_results:
        results.extend(batch_results)
        errors.extend(batch_errors)

    print(f"Total results: {len(results)}")
    print(f"Total errors: {len(errors)}")
    if errors:
        for e in errors[:5]:
            print(f"  Error: {e}")

    return len(errors) == 0


if __name__ == "__main__":
    success = asyncio.run(test_concurrent_normalize())
    if success:
        print("PASS: No race condition detected")
    else:
        print("FAIL: Race condition or errors detected")
        sys.exit(1)
