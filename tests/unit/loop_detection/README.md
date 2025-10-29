# Loop Detection Session Isolation Tests

This directory contains comprehensive test suites to ensure that loop detection maintains proper session isolation and prevents state contamination between different user sessions.

## Test Files

### `test_session_isolation.py`
Unit tests for session isolation in the `LoopDetectionProcessor`.

**Key Test Categories:**

1. **Session Independence**
   - Different sessions get different detector instances
   - State doesn't leak between sessions
   - Loop detection in one session doesn't affect another

2. **Lifecycle Management**
   - Detectors are cleaned up when sessions complete
   - Same session reuses its detector instance
   - Multiple cleanup calls are safe

3. **Concurrent Sessions**
   - Multiple concurrent sessions maintain isolation
   - Each session has its own content history

4. **Regression Prevention**
   - Tests that would FAIL if someone reverts to shared detector
   - Tests that would FAIL if state becomes global

### `../integration/test_loop_detection_session_isolation_e2e.py`
End-to-end integration tests simulating real-world scenarios.

**Key Test Categories:**

1. **Concurrent Session Scenarios**
   - One session with loop, one without
   - Many concurrent sessions (stress test)
   - Sessions with intermittent chunks

2. **Sequential Sessions**
   - Proper cleanup between sessions
   - Session restart after cleanup
   - Realistic qwen-oauth scenario

3. **Memory Management**
   - No memory leaks with many sessions
   - Cleanup on exception

## Running the Tests

```bash
# Run unit tests
pytest tests/unit/loop_detection/test_session_isolation.py -v

# Run integration tests
pytest tests/integration/test_loop_detection_session_isolation_e2e.py -v

# Run all loop detection tests
pytest tests/unit/loop_detection/ tests/integration/test_loop_detection_session_isolation_e2e.py -v
```

## Critical Assertions

These tests enforce the following guarantees:

1. **One detector per session**: Each unique session_id gets its own detector instance
2. **No state sharing**: Session A's accumulated content never appears in Session B's detector
3. **Proper cleanup**: Detectors are removed from memory when sessions complete
4. **Factory pattern**: New detectors are created via factory function, not shared instances

## Regression Detection

The tests are specifically designed to catch if someone:

1. Reverts to using a single shared detector instance
2. Stores detector state in a class variable or module-level variable
3. Forgets to clean up detectors after sessions complete
4. Breaks the factory pattern by passing detector instances directly

## Test Coverage

- ✅ Session isolation
- ✅ State accumulation within session
- ✅ State isolation between sessions
- ✅ Cleanup on completion
- ✅ Cleanup on exception
- ✅ Concurrent sessions
- ✅ Sequential sessions
- ✅ Memory leak prevention
- ✅ Factory pattern enforcement
- ✅ Fallback to default session
- ✅ Stream ID fallback

## Related Documentation

See `LOOP_DETECTION_FIX.md` in the project root for details on the session isolation bug that was fixed and why these tests are critical.
