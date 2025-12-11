# Request Deduplication

Request deduplication prevents duplicate requests from being sent to backend APIs within a configurable time window. This feature protects against rate limit exhaustion caused by client retry behavior.

## Overview

When agentic clients experience network latency or timeouts, they may re-send identical requests in rapid succession. Without deduplication, each retry consumes backend quota and can quickly exhaust rate limits.

The deduplication service:

1. **Detects duplicate requests** - Computes a content hash of each request (session ID, model, messages, tools)
2. **Swallows duplicates** - Identical requests within the dedup window are blocked with a `DuplicateRequestError` (HTTP 429)
3. **Logs blocked requests** - Each blocked duplicate is logged at WARNING level for visibility
4. **Tracks statistics** - Maintains counters for processed requests, blocked duplicates, and dedup rate

## Configuration

### CLI Parameters

```bash
# Set deduplication window in seconds (default: 3.0)
--request-dedup-window 3.0

# Disable deduplication entirely
--disable-request-dedup
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_REQUEST_DEDUP_WINDOW` | `3.0` | Time window in seconds for duplicate detection. Set to `0` to disable. |

### Configuration File

```yaml
# config/config.yaml
request_dedup_window: 3.0  # seconds
```

### Priority

Configuration values are resolved in this order (highest priority first):

1. CLI parameter (`--request-dedup-window` or `--disable-request-dedup`)
2. Environment variable (`LLM_REQUEST_DEDUP_WINDOW`)
3. Configuration file (`request_dedup_window`)
4. Default value (`3.0` seconds)

## How It Works

### Content Hashing

Each request is hashed based on:

- **Session ID** - Requests from different sessions are never considered duplicates
- **Model name** - Same message to different models is not a duplicate
- **Messages** - The full message history including roles and content
- **Tools** - Tool definitions if present

### Duplicate Detection

When a request arrives:

1. Content hash is computed
2. Cache key is formed: `{session_id}:{content_hash}`
3. If key exists in cache AND entry is within the dedup window → **DUPLICATE**
4. Otherwise, request is registered in cache and processed normally

### Garbage Collection

The service automatically cleans up expired entries:

- **Time-based cleanup** - Every 30 seconds, entries older than the dedup window are removed
- **Size-based cleanup** - When cache exceeds 10,000 entries, oldest entries are evicted
- **On-access cleanup** - Cleanup checks happen during normal request processing

## Usage Examples

### Scenario 1: Client Retry Due to Timeout

```
T=0.0s: Client sends request A → Processed normally
T=1.5s: Client retries request A (timeout) → BLOCKED (duplicate)
T=2.8s: Client retries request A again → BLOCKED (duplicate)
T=4.0s: Client sends new request B → Processed normally
```

### Scenario 2: Different Sessions

```
Session-1 sends request A → Processed normally
Session-2 sends identical request A → Processed normally (different session)
```

### Scenario 3: Window Expiration

```
T=0.0s: Request A processed
T=3.5s: Same request A sent again → Processed normally (window expired)
```

## Log Messages

When a duplicate is detected and blocked:

```
WARNING  Duplicate request swallowed: hash=a1b2c3d4 session=sess-123 model=gpt-4
```

Debug logging provides additional detail:

```
DEBUG    Duplicate detected: hash=a1b2c3d4, session=sess-123, age=1.25s
DEBUG    Request deduplication enabled with window=3.0s
DEBUG    Dedup cache cleanup: removed 15 expired entries, cache_size=42
```

## Statistics

The service tracks these metrics (accessible programmatically):

| Metric | Description |
|--------|-------------|
| `requests_processed` | Total requests checked by the dedup service |
| `duplicates_blocked` | Number of duplicate requests blocked |
| `cache_size` | Current number of entries in the dedup cache |
| `dedup_rate` | Ratio of blocked duplicates to total requests |
| `window_seconds` | Configured dedup window |
| `enabled` | Whether deduplication is active |

## Disabling Deduplication

To disable deduplication:

```bash
# Via CLI
--disable-request-dedup

# Or set window to 0
--request-dedup-window 0

# Via environment
export LLM_REQUEST_DEDUP_WINDOW=0
```

## Thread Safety

The deduplication service is fully thread-safe:

- All cache operations are protected by an asyncio lock
- Statistics reads are non-blocking (approximate values)
- Concurrent requests from multiple sessions are handled correctly

## Related Features

- **[Failure Handling](failure-handling.md)** - Automatic retry and failover for backend errors
- **[Health Checks](health-checks.md)** - Backend health monitoring and circuit breaker
- **[Session Management](session-management.md)** - Session handling and state management

## Troubleshooting

### Requests Being Blocked Unexpectedly

If legitimate requests are being blocked:

1. Check if requests are truly identical (same messages, model, tools)
2. Increase the dedup window: `--request-dedup-window 1.0`
3. Or disable deduplication: `--disable-request-dedup`

### High Duplicate Rate

A high duplicate rate (e.g., >10%) suggests client-side issues:

1. Check client timeout settings - may be too aggressive
2. Review network latency between client and proxy
3. Consider increasing client timeouts rather than disabling dedup

### Memory Usage

The cache is bounded to 10,000 entries maximum. With a 3-second window and typical request patterns, memory usage is minimal (<1MB).
