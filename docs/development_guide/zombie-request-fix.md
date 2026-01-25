# Zombie Request Deduplication Fix

## Problem: Phantom Requests After Client Shutdown

**Production Issue (2026-01-25):** After stopping OpenCode clients, the proxy continued processing new incoming HTTP requests with identical payloads. This indicated client-side retry logic continuing even after shutdown.

### Impact
- ❌ **Cost waste:** Each zombie retry consumed backend API quota (87k+ tokens per request)
- ❌ **Log pollution:** Made debugging difficult
- ❌ **False metrics:** Inflated usage statistics
- ❌ **Session confusion:** Interleaved with legitimate requests

## Root Cause

The proxy **was working correctly** - it processed all incoming HTTP requests as expected. The issue was:

1. **Streaming bypass:** Deduplication was disabled for all streaming requests
2. **Client bugs:** OpenCode's retry logic didn't clear when stopped
3. **No status tracking:** Couldn't distinguish zombie retries from legitimate 429 retries

## Solution: Status-Aware Deduplication

Enhanced `RequestDeduplicationService` to track request completion status and make intelligent duplicate decisions:

### Deduplication Matrix

| Original Status | Duplicate Arrives | Behavior | Reason |
|----------------|-------------------|----------|---------|
| **IN_FLIGHT** | Any time | ❌ BLOCKED | True parallel duplicate |
| **SUCCESS (200)** | Within window | ❌ BLOCKED | Zombie retry after success |
| **RETRIABLE_ERROR (429, 503, 502, 504, 408)** | **ANY TIME** | ✅ **ALLOWED** | **Legitimate retry** |
| **CLIENT_DISCONNECT** | Within window | ❌ BLOCKED | Zombie retry after disconnect |
| Any status | After window expires | ✅ ALLOWED | Expired, treat as new |

### Critical Guarantee

**Retries after 429/503 errors are NEVER blocked, regardless of timing.**

This ensures the fix doesn't interfere with legitimate retry workflows while preventing zombie request waste.

## Implementation Changes

### 1. Enhanced `RequestDeduplicationService`

```python
@dataclass
class TrackedRequest:
    timestamp: float
    status: RequestStatus  # IN_FLIGHT, SUCCESS, RETRIABLE_ERROR, CLIENT_DISCONNECT
    status_code: int | None = None

async def check_and_register(request, session_id):
    # CRITICAL: Always allow retries after retriable errors
    if tracked.status == RequestStatus.RETRIABLE_ERROR:
        return (False, hash)  # Not a duplicate
    
    # Block duplicates of in-flight, success, or disconnected requests
    if age < window and tracked.status in (IN_FLIGHT, SUCCESS, CLIENT_DISCONNECT):
        return (True, hash)  # Is a duplicate
```

### 2. Updated `BackendRequestManager`

- Removed streaming bypass (now dedups all requests)
- Calls `mark_request_complete()` with status code after request completes
- Handles client disconnects (`asyncio.CancelledError`)
- Preserves `x-llmproxy-no-dedup` header for opt-out

### 3. Enabled Streaming Deduplication

**Before:**
```python
if request.stream:
    return True  # Bypass deduplication
```

**After:**
```python
# Only bypass if explicitly requested via header
if headers.get("x-llmproxy-no-dedup") == "true":
    return True
return False  # Apply deduplication
```

## Configuration

No configuration changes required. The existing deduplication settings apply:

```yaml
# Default values (configured via DI registration)
deduplication:
  window_seconds: 3.0  # Block duplicates within 3 seconds
  enabled: true  # Now applies to streaming too
  max_cache_size: 10000
```

To opt out (for specific clients):
```bash
curl -H "x-llmproxy-no-dedup: true" ...
```

## Test Coverage

### Unit Tests (22/22 passed)
- ✅ `test_retry_after_429_always_allowed` - Never blocks 429 retries
- ✅ `test_retry_after_503_allowed` - Allows service unavailable retries
- ✅ `test_retry_after_success_blocked` - Blocks zombie retries after 200
- ✅ `test_retry_after_client_disconnect_blocked` - Blocks zombie retries after disconnect
- ✅ `test_parallel_duplicate_blocked` - Blocks true parallel duplicates
- ✅ `test_multiple_retries_after_429_allowed` - Allows retry loops
- ✅ `test_zombie_pattern_detection` - Reproduces production scenario

### Integration Tests (4/4 passed)
- ✅ `test_streaming_dedup_enabled_for_streaming_requests` - Streaming now dedups
- ✅ `test_streaming_dedup_bypass_via_header` - Opt-out still works
- ✅ Backend request manager integration tests

## Backward Compatibility

- ✅ Legitimate 429 retries: **Unaffected** (always allowed)
- ✅ Normal workflows: **Unaffected** (dedups only identical requests)
- ✅ Opt-out header: **Still works** (`x-llmproxy-no-dedup: true`)
- ⚠️ Breaking: Streaming requests now deduplicated (was bypassed before)

**Migration:** If clients rely on streaming bypass, add `x-llmproxy-no-dedup: true` header.

## Production Verification

The fix prevents the exact scenario from logs:

```
# Before fix:
01:53:37 - Client sends request (120 messages)
01:53:41 - Client disconnects
01:53:42 - Client sends SAME request again  ← Zombie retry
01:53:42 - Client disconnects
01:53:42 - Client sends SAME request again  ← Zombie retry
...continues indefinitely

# After fix:
01:53:37 - Client sends request (120 messages)
01:53:41 - Client disconnects → marked as CLIENT_DISCONNECT
01:53:42 - Client sends SAME request → BLOCKED (duplicate)
```

## Monitoring

Check deduplication stats via diagnostics endpoint:

```python
stats = dedup_service.get_stats()
print(f"Retries after errors: {stats.extra['retries_after_error_allowed']}")
print(f"Zombies blocked: {stats.duplicates_blocked}")
```

High `duplicates_blocked` with low `retries_after_error_allowed` indicates zombie request patterns.
