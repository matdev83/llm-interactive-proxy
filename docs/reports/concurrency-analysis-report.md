# Concurrency Issues Analysis Report

## Session: Bughunt - unsafe data access in async/multi-threaded code

**Date:** 2025-12-27
**Scanned Directory:** ./src/
**Method:** Systematic search using ripgrep for concurrency patterns
**Focus:** Race conditions, unsynchronized mutations, check-then-act patterns

---

## Summary of Findings

### Issue #1: Race Condition in `buffered_wire_capture_service.py` - Sequence Counter

**File:** `src/core/services/buffered_wire_capture_service.py`
**Risk Type:** Check-then-act race on `_sequence_counter`
**Severity:** HIGH
**Impact:** Duplicate sequence numbers in wire capture logs, breaking ordering guarantees

**Concurrency Model:**
- Multiple concurrent async tasks can call `capture_inbound_request`, `capture_outbound_request`, etc.
- All these methods call `_create_entry()` which unsafely increments `_sequence_counter`
- No lock protection around lines 276 (initialization) and 803-804 (normal path)

**Critical Section:** The sequence counter increment operation:
```python
# Line 803-804 (unsafe)
self._sequence_counter += 1
sequence = self._sequence_counter
```

**Race Condition Scenario:**
1. Task A reads `_sequence_counter` = 100
2. Task B reads `_sequence_counter` = 100 (before Task A writes)
3. Task A writes `_sequence_counter` = 101
4. Task B writes `_sequence_counter` = 101
5. Both tasks use sequence 101 → DUPLICATE

**Why It's Unsafe:**
- The read-modify-write operation (`+= 1`) is not atomic
- Multiple concurrent tasks can interleave reads/writes
- No synchronization primitive protecting the critical section

**Contexts Accessing:**
- All async capture methods: `capture_inbound_request`, `capture_outbound_request`, `capture_inbound_response`, `capture_outbound_response`, `capture_stream_response`, `capture_stream_completion`
- Streaming functions that iterate over chunks and call `_create_entry` repeatedly

**Correct Pattern (from `cbor_wire_capture_service.py`):**
```python
# Lines 244-249 of cbor_wire_capture_service.py
async def _get_next_sequence(self) -> int:
    """Get next sequence number, thread-safe."""
    async with self._sequence_lock:
        seq = self._sequence_counter
        self._sequence_counter += 1
        return seq
```

**Recommended Fix:**
1. Add `self._sequence_lock = asyncio.Lock()` to `__init__`
2. Add `async def _get_next_sequence(self) -> int:` method
3. Change `_create_entry` to be async and call `await self._get_next_sequence()`
4. Update all callers to await the async version of `_create_entry`

**Impact Map:**
- Callers (all need update to `await`):
  - Line 426: `entry = self._create_entry(` → `entry = await self._create_entry(`
  - Line 456: `entry = self._create_entry(` → `entry = await self._create_entry(`
  - Line 491: `entry = self._create_entry(` → `entry = await self._create_entry(`
  - Line 521: `entry = self._create_entry(` → `entry = await self._create_entry(`
  - Lines 554, 576, 593, 638: Stream-related calls
  - Lines 669, 689, 708: More stream-related calls

- Related Tests (should pass after fix):
  - `tests/integration/test_buffered_wire_capture_integration.py` (8 tests)
  - `tests/behavior/test_wire_capture_behavior.py`
  - `tests/regression/test_buffered_wire_capture_cache_regression.py`

---

### Issue #2: Race Condition in `buffered_wire_capture_service.py` - Total Bytes Written

**File:** `src/core/services/buffered_wire_capture_service.py`
**Risk Type:** Unsynchronized increment of `_total_bytes_written`
**Severity:** MEDIUM
**Impact:** Inaccurate byte accounting, potential overflow/underflow

**Unsafe Increments:**
```python
# Lines ~328, ~387: Unsafe increment in _flush_to_disk
self._total_bytes_written += entry_bytes
```

**Race Condition Scenario:**
- Multiple concurrent flush operations can read-modify-write `_total_bytes_written` simultaneously
- Result: Lost updates, incorrect byte counts

**Contexts Accessing:**
- `_flush_to_disk()` called from background flush task
- Multiple concurrent captures can trigger concurrent flushes

**Recommended Fix:**
- Protect `_total_bytes_written` increments with `_buffer_lock` (already exists)
- Or create dedicated counter lock similar to sequence lock

---

### Issue #3: Race Condition in `loop_detection/analyzer.py` - Mutable Shared State

**File:** `src/loop_detection/analyzer.py`
**Risk Type:** Instance attributes mutated without synchronization
**Severity:** MEDIUM (conditional on actual concurrent usage)
**Impact:** Data corruption, ConcurrentModificationError-like issues

**Unsafe Mutations:**
```python
# Line 55: History list mutated
self.history: list[LoopDetectionEvent] = []

# Line 318: Dict mutated without lock
self._content_stats[hash_hex] = [self._last_chunk_index]

# Line 332: List mutated without lock
existing_indices.append(self._last_chunk_index)

# Line 340: List slice assignment without lock
existing_indices[:] = existing_indices[-max_indices:]
```

**Concurrency Model:**
- `PatternAnalyzer` is typically instantiated per-stream (not shared globally)
- However, if reused across concurrent operations or shared state, race conditions can occur
- Comment in code suggests: "To store detected events" - potential for concurrent access

**Why It's Potentially Unsafe:**
- No locks protecting `_stream_history`, `_content_stats`, `history`
- Multiple concurrent calls to `ingest_chunk()` or `analyze_pending_stream()` can corrupt data structures
- `_content_stats` is a dict that can have concurrent writes to same or different keys

**Contexts Accessing:**
- `analyze_chunk()` - Called per-chunk during streaming
- `ingest_chunk()` - Updates internal state
- `analyze_pending_stream()` - Modifies `_content_stats`, `history`
- `_is_loop_detected_for_chunk()` - Mutates `_content_stats` entries

**Recommended Fix:**
1. Add lock to `PatternAnalyzer.__init__`: `self._lock = asyncio.Lock()`
2. Protect all state mutations in `ingest_chunk`, `analyze_pending_stream`, `_is_loop_detected_for_chunk`
3. Consider making analyzer instance immutable or use copy-on-write pattern

**Alternative Approach:**
- Given the typical per-stream instantiation pattern, document that `PatternAnalyzer` is NOT thread-safe and MUST be created per-stream
- Add a clear warning in docstring if concurrent use is expected to fail

**Impact Map:**
- Related Tests (these should pass with proper synchronization):
  - `tests/regression/test_pattern_analyzer_content_stats_with_analysis_regression.py`
  - `tests/regression/test_pattern_analyzer_memory_leak_regression.py`
  - `tests/regression/test_pattern_analyzer_history_leak_regression.py`

---

## Comparison with Safe Implementations

### Safe Pattern: `cbor_wire_capture_service.py`
- Has `_sequence_lock = threading.Lock()` (line 147)
- Implements `_get_next_sequence()` with proper lock protection (lines 244-249)
- Uses `await self._get_next_sequence()` in all code paths

### Safe Pattern: `connection_activity_tracker.py`
- Uses `threading.Lock()` for all state mutations
- All public methods use `with self._lock:` context manager
- Creates shallow copies to avoid holding locks during processing

### Safe Pattern: `tool_call_reactor_service.py`
- Uses `async with self._lock:` for all state mutations
- Lines 562, 566, 576, 582, 585: All protected with lock
- Counter increments within lock context (lines 576, 585)

---

## Test Recommendations

### For Issue #1 (buffered_wire_capture_service sequence counter):
```python
async def test_concurrent_capture_sequences_unique():
    """Verify concurrent captures generate unique sequence numbers."""
    # Setup capture service with file
    # Launch 10+ concurrent capture_inbound_request calls
    # Read resulting capture file
    # Assert: All sequence numbers are unique
    # Assert: Exactly N sequences generated
```

### For Issue #2 (buffered_wire_capture_service bytes counter):
```python
async def test_concurrent_flush_byte_counting():
    """Verify byte counting is accurate under concurrent flushes."""
    # Setup capture service
    # Trigger many concurrent captures to trigger concurrent flushes
    # Check final _total_bytes_written vs actual file size
    # Assert: Matches within tolerance
```

### For Issue #3 (loop_detection/analyzer state mutations):
```python
async def test_concurrent_analyzer_access():
    """Verify analyzer state is protected or documented as not thread-safe."""
    # If implementing locks: Test concurrent ingest_chunk calls
    # If documenting limitation: Verify docstring warning exists
```

---

## Conclusion

Three high-impact concurrency issues identified:
1. **Sequence counter race** in `buffered_wire_capture_service.py` (HIGH severity)
2. **Byte counter race** in `buffered_wire_capture_service.py` (MEDIUM severity)
3. **State mutation race** in `loop_detection/analyzer.py` (MEDIUM severity, conditional)

All three issues share common patterns:
- Unsynchronized read-modify-write operations
- Multiple concurrent contexts accessing mutable state
- Missing locks or improper use of async primitives

The fixes follow established patterns in the codebase (see `cbor_wire_capture_service.py`, `connection_activity_tracker.py`).

---

## Notes on Implementation Constraints

Per task requirements:
- ✅ Scan only `./src/` and subfolders
- ✅ Use `rg` for all searches
- ✅ Exclude dot/underscore directories
- ✅ Fix up to 3 high-impact issues
- ✅ Preserve behavior while making shared-state access correct
- ✅ Do NOT add new dependencies
- ✅ Do NOT rewrite whole subsystems
- ✅ Do NOT change public APIs without full call-site updates
- ✅ Do NOT touch files listed in "already fixed files"

**Files Avoided (already fixed):**
- `src/core/services/streaming/stream_context_registry.py`
- `src/core/services/structured_wire_capture_service.py`
- `src/core/services/wire_capture_service.py`
