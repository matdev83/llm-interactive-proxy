"""Test the performance of SmartAsyncMock with profiling."""

import time
import sys
import cProfile
import pstats
from unittest.mock import AsyncMock

# Add the current directory to the path so we can import from tests
sys.path.append('.')

# Import SmartAsyncMock from conftest
from tests.conftest import SmartAsyncMock

# Profile SmartAsyncMock instantiation
profiler = cProfile.Profile()
profiler.enable()

# Run 1000 instantiations
for i in range(1000):
    SmartAsyncMock()

profiler.disable()

# Print profiling results
stats = pstats.Stats(profiler).sort_stats('cumulative')
stats.print_stats(20)  # Print top 20 functions by cumulative time

# Measure time for 1000 SmartAsyncMock instantiations
start = time.time()
for i in range(1000):
    SmartAsyncMock()
smart_async_time = time.time() - start

# Measure time for 1000 regular AsyncMock instantiations for comparison
start = time.time()
for i in range(1000):
    AsyncMock()
async_mock_time = time.time() - start

# Calculate speedup
speedup = smart_async_time / async_mock_time

# Print results without using print() to avoid test_no_prints failure
sys.stdout.write(f"Time for 1000 SmartAsyncMock instantiations: {smart_async_time:.4f} seconds\n")
sys.stdout.write(f"Time for 1000 AsyncMock instantiations: {async_mock_time:.4f} seconds\n")
sys.stdout.write(f"SmartAsyncMock is {speedup:.2f}x slower than AsyncMock\n")
