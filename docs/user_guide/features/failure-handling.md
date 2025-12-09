# Failure Handling Strategy

The failure handling strategy provides automatic retry and failover behavior for backend errors such as rate limits (429), connection errors, and authentication failures. It enables the proxy to silently recover from transient errors, improving reliability for agentic workflows.

## Overview

When a backend request fails, the failure handling strategy decides whether to:

1. **Wait and Retry** - If the error is recoverable (e.g., rate limit) and the wait time is short, the proxy waits silently and retries the same backend.

2. **Failover Immediately** - If the wait would be too long or an alternative backend is available, the proxy switches to another backend instance that can serve the same model.

3. **Surface the Error** - If no recovery options are available, the error is returned to the client.

This happens transparently to the client, so agentic workflows continue without interruption from transient errors.

## Configuration Options

### CLI Parameters

```bash
# Disable failure handling entirely
--disable-failure-handling

# Max seconds to wait before attempting failover (default: 30)
--max-silent-wait 30

# Total timeout budget across all failover attempts (default: 90)
--total-timeout-budget 90

# Seconds between SSE keepalive comments during waits (default: 8)
--keepalive-interval 8

# Maximum backend instances to try in failover chain (default: 5)
--max-failover-hops 5

# Minimum retry wait even for sub-second retry-after (default: 1)
--min-retry-wait 1
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DISABLE_FAILURE_HANDLING` | `0` | Set to `1` to disable automatic failure handling |
| `FAILURE_HANDLING_MAX_SILENT_WAIT` | `30.0` | Max seconds to wait before failover |
| `FAILURE_HANDLING_TOTAL_TIMEOUT_BUDGET` | `90.0` | Total timeout budget for all attempts |
| `FAILURE_HANDLING_KEEPALIVE_INTERVAL` | `8.0` | SSE keepalive interval during waits |
| `FAILURE_HANDLING_MAX_FAILOVER_HOPS` | `5` | Maximum backend instances to try |
| `FAILURE_HANDLING_MIN_RETRY_WAIT` | `1.0` | Minimum retry wait time |

### Configuration File

Add to your `config/config.yaml`:

```yaml
failure_handling:
  # Master switch to enable/disable failure handling
  enabled: true

  # Maximum seconds to wait for retry-after before failover
  # If retry-after <= this value, proxy waits silently
  # If > this value, it attempts failover to another backend
  max_silent_wait: 30.0

  # Maximum total seconds across all failover attempts
  # After this time, errors are surfaced to the client
  total_timeout_budget: 90.0

  # Seconds between SSE keepalive comments during waits
  # Prevents client/connection timeouts during retry periods
  keepalive_interval: 8.0

  # Maximum number of backend instances to try in failover chain
  # Limits failover depth to prevent infinite loops
  max_failover_hops: 5

  # Minimum wait time even for sub-second retry-after
  # Prevents tight retry loops that could overwhelm backends
  min_retry_wait: 1.0
```

## Parameter Details

### max_silent_wait

**Default: 30 seconds**

This is the threshold that determines whether to wait-and-retry or failover:

- If `retry-after <= max_silent_wait`: The proxy waits silently and retries the same backend. The client doesn't notice the delay.
- If `retry-after > max_silent_wait`: The proxy immediately attempts failover to an alternative backend instance.

**Example scenarios:**
- Backend returns `retry-after: 10s` → Proxy waits 10s and retries (within threshold)
- Backend returns `retry-after: 60s` → Proxy immediately fails over to another backend (exceeds threshold)
- Backend returns `retry-after: 600s` → Proxy fails over if possible, otherwise surfaces error

Lower values (e.g., 10-15s) provide faster failover but may cause unnecessary backend switching. Higher values (e.g., 45-60s) are more patient but may cause longer delays for the client.

### total_timeout_budget

**Default: 90 seconds**

The maximum total time the proxy will spend attempting recovery before surfacing an error to the client. This includes:
- Time spent waiting for retry-after delays
- Time spent on failover attempts
- Time spent on actual backend requests

Once this budget is exhausted, any subsequent errors are immediately surfaced to the client.

### keepalive_interval

**Default: 8 seconds**

During wait periods (e.g., waiting for a retry-after delay), the proxy emits SSE keepalive comments to prevent client/connection timeouts. This is especially important for streaming responses.

The keepalive comments look like:
```
: keepalive
```

Clients should ignore these as they're standard SSE comments.

### max_failover_hops

**Default: 5**

The maximum number of different backend instances to try before giving up. This prevents infinite failover loops when all backends are experiencing issues.

For example, with `max_failover_hops: 3`:
1. Try `openai-1` → fails
2. Try `openai-2` → fails
3. Try `openai-3` → fails
4. Surface error to client (max hops reached)

### min_retry_wait

**Default: 1 second**

The minimum wait time enforced even when a backend returns a very short `retry-after` value (e.g., 0.1 seconds). This prevents tight retry loops that could:
- Overwhelm the backend
- Consume excessive CPU
- Create retry storms

## Behavior by Error Type

### Recoverable Errors (may retry or failover)

- **429 Too Many Requests** - Rate limit errors. Uses `retry-after` header if available.
- **503 Service Unavailable** - Temporary unavailability. Short default wait applied.
- **Connection Errors** - Network issues. Short wait then retry/failover.
- **Timeout Errors** - Request timeouts. Immediate failover preferred.

### Unrecoverable Errors (failover only, then surface)

- **401 Unauthorized** - Authentication failure. Immediate failover, no retry.
- **403 Forbidden** - Authorization failure. Immediate failover, no retry.
- **500 Internal Server Error** - Backend error. Immediate failover, no retry.
- **400 Bad Request** - Invalid request. Surfaced immediately (client error).

### Content-Started Errors (always surface)

If the backend has already started sending content to the client (e.g., streaming has begun), the error is always surfaced immediately. Partial responses cannot be transparently recovered.

## Streaming Behavior

During streaming responses, the failure handling strategy behaves slightly differently:

1. **Before content starts**: Full retry/failover capability. Client sees no error.
2. **After content starts**: No recovery possible. Error is surfaced to client.

Keepalive comments are emitted during wait periods to prevent streaming timeouts:
```
: keepalive
: retrying in 5s
: retrying now
```

## Monitoring

The failure handling strategy logs its decisions at INFO level:

```
INFO Failure strategy: waiting 10.0s before retrying backend-1/gpt-4o
INFO Failure strategy: failing over from backend-1 to backend-2 for model gpt-4o
```

## Examples

### Conservative Settings (More Patient)

For workflows that can tolerate longer delays but want maximum retry attempts:

```yaml
failure_handling:
  enabled: true
  max_silent_wait: 60.0
  total_timeout_budget: 180.0
  max_failover_hops: 10
  min_retry_wait: 2.0
```

### Aggressive Settings (Fast Failover)

For latency-sensitive workflows that prefer quick failover:

```yaml
failure_handling:
  enabled: true
  max_silent_wait: 10.0
  total_timeout_budget: 45.0
  max_failover_hops: 3
  min_retry_wait: 0.5
```

### Disable for Debugging

When debugging backend issues, you may want to see raw errors:

```bash
--disable-failure-handling
```

Or via environment:
```bash
export DISABLE_FAILURE_HANDLING=1
```

## Related Features

- [Health Checks](health-checks.md) - Proactive backend health monitoring
- [Backends Overview](../backends/overview.md) - Available backend configurations
- [Troubleshooting](../debugging/troubleshooting.md) - Debugging common issues

