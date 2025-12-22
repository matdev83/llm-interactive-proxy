# Memory Leak Investigation Patterns

## Patterns Already Fixed
✅ **Rate Limiter Unbounded Timestamps**: Fixed capping of `cost` parameter in `record_usage()`

## Recommended Investigation Patterns

### 1. **Event Handler Accumulation Without Cleanup**
**Pattern**: Event subscribers that are never unsubscribed
**Files to check**:
- `src/core/services/event_bus.py` - Already has `_MAX_TOTAL_HANDLERS` limit ✅
- Any service that subscribes to events dynamically (per-request handlers)
- Look for: `event_bus.subscribe()` calls without corresponding `unsubscribe()` in cleanup paths

**Investigation approach**:
```python
# Check if handlers accumulate over time
# Look for patterns like:
async def handle_request():
    async def per_request_handler(event):
        # ...
    event_bus.subscribe(SomeEvent, per_request_handler)
    # Missing: event_bus.unsubscribe() in finally block
```

**Risk areas**:
- Request-scoped event handlers
- Middleware that subscribes to events
- Error handlers that subscribe dynamically

---

### 2. **Streaming Context Registry - Stale Stream States**
**Pattern**: Stream states that never complete (network failures, client disconnects)
**Files to check**:
- `src/core/services/streaming/stream_context_registry.py` - Has TTL cleanup ✅
- But verify: Is TTL cleanup actually being called frequently enough?
- Check: What happens if streams are created faster than cleanup runs?

**Investigation approach**:
```python
# Monitor stream state count over time under load
# Check if cleanup is called on every access or only periodically
# Verify max_states limit is enforced before adding new states
```

**Risk areas**:
- High-frequency stream creation
- Network timeouts that don't trigger cleanup
- Streams that never send `is_done=True`

---

### 3. **Async Task Accumulation**
**Pattern**: Background tasks that are created but never awaited/cleaned up
**Files to check**:
- `src/core/services/response_processor_service.py` - Has `_MAX_BACKGROUND_TASKS` ✅
- But verify: Are tasks properly removed when they complete?
- Check: What about tasks that never complete (hanging tasks)?

**Investigation approach**:
```python
# Look for patterns like:
task = asyncio.create_task(some_async_function())
# Missing: task.add_done_callback(cleanup) or await/track task
```

**Risk areas**:
- Fire-and-forget async tasks
- Tasks created in loops without tracking
- Exception handlers that create tasks

---

### 4. **Dictionary/Set Growth Without Bounds**
**Pattern**: Dictionaries that accumulate entries without cleanup
**Files to check**:
- Any service with `dict[str, Any]` that grows over time
- Session tracking dictionaries
- Cache dictionaries without TTL or size limits

**Investigation approach**:
```python
# Search for patterns like:
self._cache: dict[str, Any] = {}
# Without: maxsize, TTL, or cleanup logic

# Look for:
- Session ID -> data mappings
- Request ID -> response mappings  
- Connection ID -> state mappings
```

**Risk areas**:
- Session repositories (check if sessions are cleaned up)
- Request/response correlation dictionaries
- WebSocket connection state dictionaries

---

### 5. **Callback/Closure Accumulation**
**Pattern**: Callbacks registered on objects that hold references
**Files to check**:
- Any code using `add_done_callback()`, `add_listener()`, etc.
- Weak references that might not be weak enough

**Investigation approach**:
```python
# Look for:
task.add_done_callback(lambda: self._cleanup())
# Problem: lambda holds reference to self, preventing GC

# Better:
task.add_done_callback(weakref.ref(self._cleanup))
```

**Risk areas**:
- Task completion callbacks
- Event listeners
- Signal handlers

---

### 6. **Circular References in Complex Objects**
**Pattern**: Objects that reference each other preventing GC
**Files to check**:
- Domain models with bidirectional relationships
- Services that hold references to each other
- Context objects that hold references to parent contexts

**Investigation approach**:
```python
# Use gc module to detect:
import gc
gc.collect()
leaks = [obj for obj in gc.get_objects() if isinstance(obj, YourClass)]
# Check if count grows over time
```

**Risk areas**:
- Request context objects
- Session objects with parent references
- Middleware chains with circular references

---

### 7. **Generator/Iterator Accumulation**
**Pattern**: Generators that are created but never consumed
**Files to check**:
- Streaming response processors
- Async generators that are created but not awaited
- Iterator chains that hold references

**Investigation approach**:
```python
# Look for:
async def process_stream():
    gen = some_generator()
    # Missing: await or close generator
    return gen  # Generator object accumulates
```

**Risk areas**:
- Streaming response handlers
- Async generators in middleware
- Iterator adapters

---

### 8. **Thread-Local Storage Accumulation**
**Pattern**: Thread-local variables that accumulate data
**Files to check**:
- Any use of `threading.local()`
- Context variables that aren't cleared

**Investigation approach**:
```python
# Check for:
thread_local = threading.local()
thread_local.data = []  # Accumulates per thread
# Missing: cleanup when thread ends
```

**Risk areas**:
- Request context storage
- Per-thread caches
- Thread-local logging contexts

---

### 9. **Weak Reference Dictionary Growth**
**Pattern**: WeakKeyDictionary/WeakValueDictionary that grows unexpectedly
**Files to check**:
- Any use of `weakref.WeakKeyDictionary` or `WeakValueDictionary`
- Verify: Are keys/values being held by other references?

**Investigation approach**:
```python
# Weak dicts only work if no other references exist
# If objects are referenced elsewhere, weak dict grows
weak_dict = weakref.WeakKeyDictionary()
weak_dict[obj] = data
# Problem: If obj is referenced elsewhere, weak dict doesn't help
```

**Risk areas**:
- Event bus handlers (already uses WeakSet ✅)
- Cache implementations using weak refs
- Observer patterns with weak references

---

### 10. **Exception Traceback Accumulation**
**Pattern**: Exceptions that hold references to large tracebacks
**Files to check**:
- Exception handlers that store exceptions
- Error logging that keeps exception objects
- Retry mechanisms that store failed exceptions

**Investigation approach**:
```python
# Look for:
self._errors: list[Exception] = []
# Problem: Exceptions hold full tracebacks

# Better:
self._error_messages: list[str] = []  # Store messages only
```

**Risk areas**:
- Error aggregation services
- Retry coordinators
- Exception normalizers that cache exceptions

---

## Investigation Tools & Techniques

### 1. **Memory Profiling**
```python
# Use memory_profiler or tracemalloc
import tracemalloc
tracemalloc.start()
# ... run code ...
snapshot = tracemalloc.take_snapshot()
top_stats = snapshot.statistics('lineno')
for stat in top_stats[:10]:
    print(stat)
```

### 2. **Object Count Monitoring**
```python
# Monitor object counts over time
import gc
def count_objects_by_type():
    counts = {}
    for obj in gc.get_objects():
        t = type(obj).__name__
        counts[t] = counts.get(t, 0) + 1
    return sorted(counts.items(), key=lambda x: x[1], reverse=True)
```

### 3. **Repro Scripts**
Create scripts that simulate high-load scenarios:
- Many concurrent requests
- Long-running sessions
- Rapid connection churn
- Large payloads

### 4. **Load Testing with Memory Monitoring**
- Run load tests while monitoring memory
- Look for steady growth over time
- Check for memory that doesn't return to baseline

---

## High-Priority Areas Based on Codebase Architecture

### 1. **Streaming Response Processing**
- Many stream states created per request
- Verify cleanup on stream completion
- Check for streams that never complete

### 2. **Session Management**
- Session dictionaries that grow
- Session-scoped caches
- Session event handlers

### 3. **Event Bus Subscriptions**
- Per-request event handlers
- Dynamic subscriptions without cleanup
- Event handlers that hold request context

### 4. **Backend Connection Pooling**
- Connection state dictionaries
- Retry state tracking
- Failover state accumulation

### 5. **Wire Capture Buffers**
- CBOR capture buffers per session
- Verify buffers are cleared after capture
- Check for buffers that never flush

---

## Recommended Next Steps

1. **Create monitoring script** to track object counts over time
2. **Add memory profiling** to integration tests
3. **Review event handler lifecycle** - ensure cleanup in all paths
4. **Check streaming cleanup** - verify TTL cleanup is effective
5. **Audit session cleanup** - ensure sessions are removed when done

---

## Files to Prioritize for Review

Based on the codebase scan, these files warrant closer inspection:

1. `src/core/services/event_bus.py` - Verify handler cleanup in all code paths
2. `src/core/services/streaming/stream_context_registry.py` - Verify TTL cleanup frequency
3. `src/core/services/response_processor_service.py` - Verify task cleanup
4. `src/core/memory/capture_buffer.py` - Verify buffer cleanup on session end
5. `src/core/services/async_usage_write_queue.py` - Verify pending records cleanup
6. `src/codebuff/connection_manager.py` - Verify connection cleanup
7. Any service with per-request state dictionaries

---

## Pattern Detection Script

Consider creating a script to detect these patterns automatically:

```python
# patterns_to_check.py
import ast
import re

def find_unbounded_dicts(file_path):
    """Find dict initializations without size limits."""
    # Look for: self._cache = {} without maxsize/TTL
    
def find_missing_cleanup(file_path):
    """Find append/extend without corresponding cleanup."""
    # Look for: .append() without .pop() or cleanup
    
def find_event_subscriptions(file_path):
    """Find event subscriptions without unsubscriptions."""
    # Look for: subscribe() without unsubscribe()
```
