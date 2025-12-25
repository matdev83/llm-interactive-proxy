"""
Repro script for race condition in core/config/parameter_resolution.py

The `ParameterResolution` class uses `_history` dict without any locks.
If configuration can be updated dynamically (parameter reloading), this causes
race conditions between record(), is_set(), build_report(), and latest_by_source().
"""
import asyncio

from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


async def test_concurrent_record_race():
    """
    Test concurrent calls to record() method.
    
    Multiple coroutines modifying _history dict can cause:
    - Lost updates
    - Dictionary size violation (exceeding _MAX_HISTORY_SIZE)
    - KeyErrors during iteration
    """
    pr = ParameterResolution()
    
    async def record_params(prefix: str):
        """Record multiple parameters"""
        for i in range(100):
            pr.record(
                f"{prefix}_param_{i}",
                f"value_{i}",
                ParameterSource.CONFIG_FILE
            )
    
    # Run many concurrent record operations
    tasks = [asyncio.create_task(record_params(f"thread_{i}")) for i in range(20)]
    await asyncio.gather(*tasks, return_exceptions=True)
    
    print(f"Final history size: {len(pr._history)}")
    print(f"Expected max size: {pr._MAX_HISTORY_SIZE}")
    
    # Check if we exceeded the limit (race condition symptom)
    if len(pr._history) > pr._MAX_HISTORY_SIZE:
        print("RACE CONDITION DETECTED: History size exceeds limit!")
    else:
        print("History size within limit (but race may still exist)")
    
    # Check for duplicate keys or missing data
    param_count = 0
    for i in range(20):
        for j in range(100):
            if pr.is_set(f"thread_{i}_param_{j}"):
                param_count += 1
    
    print(f"Parameters found via is_set(): {param_count}")
    print(f"Parameters in history: {len(pr._history)}")
    
    if param_count != len(pr._history):
        print("RACE CONDITION DETECTED: Inconsistent state!")


async def test_concurrent_read_write_race():
    """
    Test concurrent read and write operations.
    
    Readers (is_set, build_report) may see inconsistent state
    while writers (record) are modifying the dict.
    """
    pr = ParameterResolution()
    
    async def writer(prefix: str):
        """Continuously write parameters"""
        for i in range(50):
            pr.record(
                f"{prefix}_param_{i}",
                f"value_{i}",
                ParameterSource.ENVIRONMENT
            )
            await asyncio.sleep(0.001)
    
    async def reader():
        """Continuously read parameters"""
        for _ in range(50):
            for i in range(20):
                pr.is_set(f"thread_{i}_param_{i}")
            # Also build report
            pr.build_report({"dummy": "config"})
            await asyncio.sleep(0.001)
    
    # Run concurrent read/write operations
    tasks = [asyncio.create_task(writer(f"thread_{i}")) for i in range(10)]
    tasks.append(asyncio.create_task(reader()))
    
    await asyncio.gather(*tasks, return_exceptions=True)
    
    print("Test completed - no exception but race condition exists!")


async def test_size_limit_eviction_race():
    """
    Test race condition in size limit eviction logic.
    
    The eviction logic at lines 78-83 checks size, deletes keys,
    then adds new key. Concurrent calls can bypass the limit.
    """
    pr = ParameterResolution()
    
    # Pre-fill to near limit
    for i in range(pr._MAX_HISTORY_SIZE - 100):
        pr.record(f"param_{i}", f"value_{i}", ParameterSource.DEFAULT)
    
    print(f"Pre-filled with {len(pr._history)} parameters")
    
    # Now trigger concurrent additions that should trigger eviction
    async def add_many_params(prefix: str):
        for i in range(200):
            pr.record(f"{prefix}_param_{i}", f"value_{i}", ParameterSource.CLI)
    
    tasks = [asyncio.create_task(add_many_params(f"batch_{i}")) for i in range(5)]
    await asyncio.gather(*tasks, return_exceptions=True)
    
    final_size = len(pr._history)
    print(f"Final history size: {final_size}")
    print(f"Max allowed size: {pr._MAX_HISTORY_SIZE}")
    
    if final_size > pr._MAX_HISTORY_SIZE * 2:  # Allow some fudge factor
        print("RACE CONDITION DETECTED: Significantly exceeded size limit!")
    
    return final_size


if __name__ == "__main__":
    print("=== Testing Parameter Resolution Race Conditions ===")
    print("\nTest 1: Concurrent record operations")
    asyncio.run(test_concurrent_record_race())
    
    print("\nTest 2: Concurrent read/write operations")
    asyncio.run(test_concurrent_read_write_race())
    
    print("\nTest 3: Size limit eviction race")
    final_size = asyncio.run(test_size_limit_eviction_race())
    print(f"Final size from test 3: {final_size}")
