# Race Condition Fix Summary

## Issue #1: DI Container Singleton/Scoped Instance Caching Race

**File:** `src/core/di/container.py`

**Race Condition:**
Multiple concurrent `get_service()` calls can create duplicate singleton/scoped instances because there's no lock protecting the check-then-act sequence in `_get_service()`. Multiple threads can simultaneously:
1. Check if instance exists (returns False)
2. Both create and store new instance
3. Result: Multiple instances created for what should be a singleton

**Fix Applied:**
- Added `threading.Lock` to `ServiceProvider.__init__()` 
- Added `threading.Lock` to `ServiceScope.__init__()`
- Protected `_singleton_instances` and `scope._instances` dictionary access with locks
- Protected check-then-act sequence to ensure atomicity

**Changes:**
- Line 3: Added `import threading`
- Lines 52, 76: Added `self._lock = threading.Lock()` in `__init__` methods
- Lines 209-219, 234-242: Wrapped singleton/scoped instance creation/caching in `with self._lock:` blocks

**Files Modified:**
- `src/core/di/container.py`

**Repro Script:**
- `dev/artifacts/test_di_container_race.py` - Demonstrates the race condition
- `tests/regression/test_di_container_thread_safety.py` - Regression tests


## Issue #2: ConcurrencyGuard Active Operations Counting Race

**File:** `src/core/services/production_concurrency_guard.py`

**Race Condition:**
`ConcurrencyGuard.acquire()` checks `len(self._active_operations)` and increments `self._rejected_operations` without locking. Multiple concurrent calls can have inconsistent views leading to:
- Race in counting operations
- Race in checking limits
- Duplicate operation IDs being added

**Fix Applied:**
- Added `self._operation_counter = 0` for atomic operation ID generation
- Protected `_active_operations` set operations with `self._lock`
- Protected total_operations increment with same lock
- Protected rejected_operations increment with same lock

**Changes:**
- Line 24: Added `self._operation_counter = 0` in `__init__`
- Lines 328-349: Wrapped entire check-then-act logic in `with self._lock:` block
- Lines 341-348: Protected add operation and increment counters
- Lines 353-357: Protected discard with same lock

**Files Modified:**
- `src/core/services/production_concurrency_guard.py`

**Repro Script:**
- `dev/artifacts/test_concurrency_guard_race.py` - Demonstrates the race condition
- `tests/regression/test_concurrency_guard_thread_safety.py` - Regression tests


## Summary
- 2 race conditions found and fixed
- Both issues involved check-then-act patterns without proper synchronization
- Fixed by adding thread locks to protect shared state
- Regression tests created for both issues
- All changes verified with ruff linting
