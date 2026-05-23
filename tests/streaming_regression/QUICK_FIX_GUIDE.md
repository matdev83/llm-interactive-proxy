# Quick Fix Guide - Loop Detection Interference

## Problem

Streaming regression tests are failing because the loop detector is cancelling responses when it detects repeated SSE chunks as a "loop pattern".

## Evidence

```
WARNING  src.loop_detection.hybrid_detector:hybrid_detector.py:282 Long pattern loop detected: 3 repetitions of 153-char pattern
```

Test receives:
```
"[Response cancelled: Loop detected - Pattern 'Long pattern detected: data: {...' repeated 3 times]"
```

## Root Cause

The loop detector is registered in the DI container during infrastructure stage initialization, regardless of the `LOOP_DETECTION_ENABLED` configuration setting.

## Solution Options

### Option 1: Conditional Registration (Recommended)

Modify `src/core/app/stages/infrastructure.py` around line 160:

```python
# Check config before registering
if config.loop_detection_enabled:
    def loop_detector_factory(provider: IServiceProvider) -> HybridLoopDetector:
        return _create_hybrid_loop_detector()

    services.add_transient(
        HybridLoopDetector, implementation_factory=loop_detector_factory
    )
    services.add_transient(
        cast(type, ILoopDetector), implementation_factory=loop_detector_factory
    )
    logger.debug("Registered HybridLoopDetector with DI container")
else:
    # Register a no-op loop detector for tests
    def noop_detector_factory(provider: IServiceProvider) -> ILoopDetector:
        from src.loop_detection.detector import NoOpLoopDetector
        return NoOpLoopDetector()
    
    services.add_transient(
        cast(type, ILoopDetector), implementation_factory=noop_detector_factory
    )
    logger.debug("Loop detection disabled, registered NoOpLoopDetector")
```

### Option 2: Skip Middleware Application

Modify `src/core/app/stages/processor.py` around line 197:

```python
# Only add loop detection middleware if enabled
if config.loop_detection_enabled:
    logger.debug("Added loop detection middleware")
    # ... existing middleware registration
else:
    logger.debug("Loop detection disabled, skipping middleware")
```

### Option 3: Test-Specific Bypass

Create a test-specific loop detector that never triggers:

```python
# In tests/streaming_regression/conftest.py
import pytest
from unittest.mock import Mock

@pytest.fixture(autouse=True)
def disable_loop_detection(monkeypatch):
    """Disable loop detection for streaming tests."""
    # Mock the loop detector to never detect loops
    mock_detector = Mock()
    mock_detector.process_chunk.return_value = (False, None)
    mock_detector.reset.return_value = None
    
    # Patch the detector in DI container
    # ... implementation details
```

## Recommended Implementation

**Option 1** is recommended because:
1. Respects the configuration setting
2. Works for all tests, not just streaming tests
3. Doesn't require test-specific mocking
4. Maintains clean separation of concerns

## Implementation Steps

1. Create `NoOpLoopDetector` class if it doesn't exist:

```python
# In src/loop_detection/detector.py
class NoOpLoopDetector(ILoopDetector):
    """No-op loop detector for testing."""
    
    def process_chunk(self, chunk: str) -> tuple[bool, str | None]:
        return False, None
    
    def reset(self) -> None:
        pass
```

2. Modify infrastructure stage as shown in Option 1

3. Verify tests pass:

```bash
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/test_streaming_core.py::test_openai_streaming_incremental_delivery -v
```

## Testing the Fix

After implementing the fix:

```bash
# Set environment variable
$env:LOOP_DETECTION_ENABLED="false"

# Run single test
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/test_streaming_core.py::test_openai_streaming_incremental_delivery -v

# Run all streaming tests
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/ -v

# Verify loop detection still works when enabled
$env:LOOP_DETECTION_ENABLED="true"
./.venv/Scripts/python.exe -m pytest tests/integration/test_loop_detection.py -v
```

## Expected Outcome

After fix:
- Streaming tests pass with `LOOP_DETECTION_ENABLED=false`
- Loop detection tests pass with `LOOP_DETECTION_ENABLED=true`
- No interference between features
- Clean test output without loop detection warnings

## Verification

Test should show:
```
tests/streaming_regression/test_streaming_core.py::test_openai_streaming_incremental_delivery PASSED
```

With logs showing:
```
DEBUG Loop detection disabled, registered NoOpLoopDetector
```

Instead of:
```
WARNING Long pattern loop detected: 3 repetitions of 153-char pattern
```
