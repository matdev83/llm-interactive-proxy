# Memory Leak Fix Candidates - Summary

## ✅ Already Fixed
1. **Rate Limiter Unbounded Timestamps** - Fixed in `src/core/services/rate_limiter.py`

---

## 🔴 High Priority: PromptHandler Active Requests Dictionary

### Issue
**File**: `src/codebuff/handlers/prompt_handler.py:56`
**Current State**: `self._active_requests: dict[str, asyncio.Task] = {}` exists but is **never populated**

### Analysis
- Dictionary is defined but tasks are never added to it
- `cancel_request()` method tries to use it but will always find nothing
- **Current impact**: Not a leak (nothing accumulates), but it's a bug
- **Future risk**: If someone fixes the bug by adding task tracking, they must also add cleanup

### Why This Matters
The `cancel_request()` method suggests the intent was to track active streaming requests for cancellation. If this functionality is implemented later without proper cleanup, it will leak.

### Recommended Fix
**Option 1**: Remove unused dictionary (if cancellation isn't needed)
**Option 2**: Properly implement with cleanup (if cancellation is needed)

```python
# Add max size limit
_MAX_ACTIVE_REQUESTS = 1000

async def _process_streaming_response(...):
    # Wrap streaming in a task for cancellation support
    async def _stream_task():
        try:
            # ... existing streaming logic ...
        finally:
            # Always cleanup on completion
            self._active_requests.pop(prompt_id, None)
    
    # Create and track task
    task = asyncio.create_task(_stream_task())
    self._active_requests[prompt_id] = task
    
    # Enforce max size
    if len(self._active_requests) > _MAX_ACTIVE_REQUESTS:
        await self._cleanup_completed_requests()
    
    try:
        await task
    except asyncio.CancelledError:
        raise

async def _cleanup_completed_requests(self):
    """Remove completed tasks to prevent accumulation."""
    completed = [
        prompt_id for prompt_id, task in self._active_requests.items()
        if task.done()
    ]
    for prompt_id in completed:
        self._active_requests.pop(prompt_id, None)
    
    # If still over limit after cleanup, cancel oldest
    if len(self._active_requests) > _MAX_ACTIVE_REQUESTS:
        oldest_id = next(iter(self._active_requests))
        await self.cancel_request(oldest_id)
```

**Priority**: HIGH (preventive fix to avoid future leak)

---

## 🟡 Medium Priority: Investigation Areas

### 1. Event Handler Lifecycle
**Pattern**: Dynamic event subscriptions without cleanup
**Risk**: Per-request handlers that accumulate
**Action**: Review all `event_bus.subscribe()` calls for corresponding `unsubscribe()`

### 2. Streaming Context Registry Cleanup Frequency  
**File**: `src/core/services/streaming/stream_context_registry.py`
**Question**: Is TTL cleanup effective when streams are created faster than accessed?
**Action**: Verify cleanup runs even when registry isn't accessed

### 3. Session Dictionary Growth
**Pattern**: Session tracking dictionaries
**Risk**: Sessions that never get cleaned up
**Action**: Monitor session count over time, verify TTL cleanup

---

## 📊 Detection Script Results

The detection script found **969 files** with potential patterns, but most are **false positives**:
- Temporary lists created per-request (not accumulators)
- Request-scoped dictionaries (discarded after use)
- Small, bounded data structures

**Key Insight**: Focus on **class-level accumulators**, not temporary variables.

---

## 🎯 Recommended Next Steps

1. **Fix PromptHandler** - Add proper task tracking with cleanup (or remove unused dict)
2. **Create monitoring script** - Track object counts over time
3. **Review event handlers** - Ensure cleanup in all code paths
4. **Load testing** - Monitor memory under high load scenarios

---

## Testing Strategy

For each fix:
1. Create repro script showing the issue
2. Apply fix
3. Verify fix prevents growth
4. Run existing tests
5. Add regression test
