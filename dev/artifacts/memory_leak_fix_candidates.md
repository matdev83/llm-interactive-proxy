# Memory Leak Fix Candidates

## Analysis Summary

After running the detection script and manual review, here are the candidates for fixes:

---

## ✅ CONFIRMED LEAK #1: Rate Limiter (ALREADY FIXED)
**File**: `src/core/services/rate_limiter.py`
**Status**: ✅ Fixed
**Issue**: Unbounded timestamp list growth when `cost` parameter is very large
**Fix**: Added capping logic to limit timestamps based on rate limit

---

## 🔴 HIGH PRIORITY: Active Requests Dictionary in PromptHandler

### File: `src/codebuff/handlers/prompt_handler.py`
**Line**: 56
**Issue**: `self._active_requests: dict[str, asyncio.Task] = {}` accumulates tasks without cleanup

### Problem Analysis
- Tasks are added to `_active_requests` but never removed when they complete normally
- Tasks are only removed in `cancel_request()` method (explicit cancellation)
- If a request completes successfully, the task remains in the dict forever
- This causes unbounded growth of completed task objects in memory

### Current Code
```python
self._active_requests: dict[str, asyncio.Task] = {}

async def handle_prompt(...):
    # Task is created but never added to _active_requests!
    # This is actually a bug - tasks aren't being tracked at all
    
async def cancel_request(self, prompt_id: str):
    task = self._active_requests.get(prompt_id)
    if task:
        task.cancel()
        del self._active_requests[prompt_id]
```

### Root Cause
Looking at the code, tasks are created in `_stream_response()` but **never actually added to `_active_requests`**. However, if this dictionary is meant to track active requests, it should:
1. Add tasks when they start
2. Remove tasks when they complete (success or failure)
3. Have a max size limit
4. Clean up completed tasks periodically

### Recommended Fix
```python
# Add max size and cleanup
_MAX_ACTIVE_REQUESTS = 1000

async def _stream_response(...):
    # Create task wrapper that auto-cleans up
    async def _stream_with_cleanup():
        try:
            # ... existing streaming logic ...
        finally:
            # Always remove from active requests
            self._active_requests.pop(prompt_id, None)
    
    # Add to active requests BEFORE starting
    task = asyncio.create_task(_stream_with_cleanup())
    self._active_requests[prompt_id] = task
    
    # Enforce max size
    if len(self._active_requests) > _MAX_ACTIVE_REQUESTS:
        await self._cleanup_completed_requests()
    
    try:
        await task
    except asyncio.CancelledError:
        # Already cleaned up in finally
        raise

async def _cleanup_completed_requests(self):
    """Remove completed tasks from active requests."""
    completed = [
        prompt_id for prompt_id, task in self._active_requests.items()
        if task.done()
    ]
    for prompt_id in completed:
        self._active_requests.pop(prompt_id, None)
    
    # If still over limit, cancel oldest
    if len(self._active_requests) > _MAX_ACTIVE_REQUESTS:
        # Cancel oldest (FIFO)
        oldest_id = next(iter(self._active_requests))
        await self.cancel_request(oldest_id)
```

**Priority**: HIGH - This is a real leak if tasks are ever added to the dict

---

## 🟡 MEDIUM PRIORITY: Performance Tracker Markers (FALSE POSITIVE)

### File: `src/performance_tracker.py`
**Line**: 34
**Issue**: `self._markers: dict[str, float] = {}` flagged as unbounded

### Analysis
- ✅ **NOT A LEAK**: This is a per-request dataclass instance
- ✅ Markers dict is small (only phase start times, ~4-5 entries max)
- ✅ Instance is created per request and discarded after logging
- ✅ No accumulation across requests

### Verdict
**False positive** - No fix needed. The detection script flagged this because it's a dict without explicit bounds, but the lifecycle is request-scoped.

---

## 🟡 MEDIUM PRIORITY: List Append Operations (Mostly False Positives)

### Files Found:
- `src/performance_tracker.py` - `parts.append()` in `_format_timing_parts()`
- `src/connectors/openai_codex.py` - `sanitized_sections.append()`
- `src/connectors/openai_codex_config.py` - `errors.extend()`

### Analysis
All of these are:
- ✅ Temporary lists created per-request/call
- ✅ Small, bounded size (typically < 10 items)
- ✅ Discarded after use
- ✅ Not class-level accumulators

### Verdict
**False positives** - These are temporary lists, not accumulators. No fix needed.

---

## 🔍 INVESTIGATION NEEDED: Other Potential Areas

### 1. Event Handler Accumulation
**Pattern**: Look for dynamic event subscriptions without cleanup
**Files to check**:
- Any middleware that subscribes to events per-request
- Services that create event handlers dynamically

**Investigation approach**:
```python
# Search for:
event_bus.subscribe(SomeEvent, handler)
# Without corresponding:
event_bus.unsubscribe(SomeEvent, handler)
```

### 2. Streaming Context Registry TTL Effectiveness
**File**: `src/core/services/streaming/stream_context_registry.py`
**Question**: Is TTL cleanup called frequently enough?
- Cleanup is called on every access (`_maybe_cleanup_expired()`)
- But what if streams are created faster than accessed?
- Verify: Does cleanup run even when no one accesses the registry?

### 3. Session Dictionary Growth
**Pattern**: Session tracking dictionaries
**Files to check**:
- Session repositories
- Session-scoped caches
- Connection managers with session state

**Investigation approach**:
- Monitor session count over time
- Check if sessions are cleaned up on disconnect/timeout
- Verify TTL cleanup is effective

---

## Recommended Action Plan

### Immediate Fixes (High Priority)
1. ✅ **Rate Limiter** - Already fixed
2. 🔴 **PromptHandler Active Requests** - Fix task cleanup

### Investigation Tasks (Medium Priority)
1. Review event handler lifecycle - ensure cleanup in all code paths
2. Verify streaming context registry cleanup frequency
3. Monitor session dictionary growth under load
4. Check for per-request event subscriptions

### Monitoring Setup
1. Add memory profiling to integration tests
2. Create monitoring script to track object counts over time
3. Set up alerts for dictionary/list growth beyond thresholds

---

## Testing Strategy

For each fix candidate:
1. Create repro script showing unbounded growth
2. Apply fix
3. Verify fix prevents growth
4. Run existing tests to ensure no regressions
5. Add specific test for the leak scenario

---

## Notes

- Most findings from the detection script are false positives (temporary lists, request-scoped objects)
- The script is useful for finding patterns but requires manual review
- Focus on class-level accumulators, not temporary variables
- Pay special attention to async tasks and event handlers
