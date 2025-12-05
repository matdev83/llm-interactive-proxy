# Connection Activity Monitoring

The LLM Proxy provides real-time visibility into active connections through backend connectors. This feature is useful for debugging, monitoring traffic patterns, and understanding system load.

## Configuration

Activity monitoring is **disabled by default** for performance reasons. When enabled, it tracks active connections with minimal overhead using thread-safe atomic operations.

### Enabling Activity Tracking

Activity tracking can be enabled via CLI flag, environment variable, or config file. The precedence order is: CLI flag > environment variable > config file.

#### CLI Flag (Highest Priority)

```bash
.venv/Scripts/python.exe -m src.core.cli --enable-activity-tracking
```

#### Environment Variable

```bash
# Linux/macOS
export ENABLE_ACTIVITY_TRACKING=1

# Windows PowerShell
$env:ENABLE_ACTIVITY_TRACKING = "1"

# Windows CMD
set ENABLE_ACTIVITY_TRACKING=1
```

#### Config File (config/config.yaml)

```yaml
enable_activity_tracking: true
```

### Verifying Configuration

You can verify that activity tracking is enabled by checking the diagnostics endpoint:

```bash
curl http://localhost:8000/v1/diagnostics | jq '.activity_tracking_enabled'
```

Returns `true` if enabled, `false` if disabled.

### Performance Considerations

When disabled (default), activity tracking has zero overhead - the tracker is not registered in the DI container and no tracking code runs.

When enabled, the overhead is minimal:
- O(1) counter updates using `threading.Lock`
- Shallow copies for snapshots to minimize lock contention
- No per-chunk logging unless DEBUG level is enabled

## Use Cases

1. **Debugging**: Identify stuck or long-running requests by monitoring connection duration
2. **Traffic Analysis**: Understand which backends and models are most active
3. **Load Monitoring**: Track concurrent connections to detect capacity issues
4. **Performance Tuning**: Identify slow backends by comparing RX/TX rates

## Usage Examples

### Query Activity via curl

```bash
# Get full diagnostics with activity data
curl http://localhost:8000/v1/diagnostics | jq '.instances[].activity'

# Get just the activity summary
curl http://localhost:8000/v1/diagnostics/activity
```

### Monitor with the CLI Tool

```bash
# Real-time monitoring
.venv/Scripts/python.exe scripts/inspect_activity.py --watch

# One-time check with custom endpoint
.venv/Scripts/python.exe scripts/inspect_activity.py http://myproxy:9000
```

### Programmatic Access

```python
from src.core.services.connection_activity_tracker import get_activity_tracker

tracker = get_activity_tracker()
snapshot = tracker.get_global_snapshot()

print(f"Active connections: {snapshot.total_active_connections}")
print(f"Total RX: {snapshot.total_bytes_rx} bytes")
print(f"Total TX: {snapshot.total_bytes_tx} bytes")
```

## Overview

Activity monitoring tracks:

- **Active Connections**: Currently transmitting streaming and non-streaming requests
- **RX/TX Counters**: Bytes received from backend and transmitted to client
- **Session Isolation**: Each connection is tracked by its unique session ID
- **Per-Backend Metrics**: Activity is aggregated per backend instance

## Accessing Activity Data

### Via Diagnostics API

The `/v1/diagnostics` endpoint includes activity information for each backend instance:

```bash
curl http://localhost:8000/v1/diagnostics
```

Response includes:

```json
{
  "timestamp": 1701792000.123,
  "instances": [
    {
      "name": "openai.1",
      "connector_type": "openai",
      "is_rate_limited": false,
      "is_functional": true,
      "validation_errors": [],
      "models": [...],
      "activity": {
        "active_connections": 2,
        "connections": [
          {
            "session_id": "abc123...",
            "connection_type": "streaming",
            "started_at": 1701791990.456,
            "duration_seconds": 9.667,
            "model": "gpt-4",
            "bytes_rx": 15360,
            "bytes_tx": 14820
          }
        ],
        "total_bytes_rx": 15360,
        "total_bytes_tx": 14820
      }
    }
  ],
  "global_activity": {
    "total_active_connections": 2,
    "total_bytes_rx": 32000,
    "total_bytes_tx": 31500
  }
}
```

### Lightweight Activity Endpoint

For polling scenarios, use the dedicated activity endpoint:

```bash
curl http://localhost:8000/v1/diagnostics/activity
```

Response:

```json
{
  "total_active_connections": 2,
  "total_bytes_rx": 32000,
  "total_bytes_tx": 31500
}
```

## CLI Tool: inspect_activity.py

A command-line tool is provided for real-time activity monitoring:

```bash
# One-time snapshot
.venv/Scripts/python.exe scripts/inspect_activity.py

# Watch mode (auto-refresh)
.venv/Scripts/python.exe scripts/inspect_activity.py --watch

# Custom refresh interval (2 seconds)
.venv/Scripts/python.exe scripts/inspect_activity.py --watch --interval 2

# Raw JSON output
.venv/Scripts/python.exe scripts/inspect_activity.py --raw

# Custom proxy URL
.venv/Scripts/python.exe scripts/inspect_activity.py http://localhost:9000
```

### Watch Mode

When the `rich` library is installed, watch mode provides a live-updating table:

```
┌─────────────────────────────── Connection Activity ────────────────────────────────┐
│ Active Connections: 2  |  Total RX: 15.0 KB  |  Total TX: 14.5 KB  |  Updated: 14:30:05 │
└────────────────────────────────────────────────────────────────────────────────────┘

                              Active Connections
┌───────────┬───────────────┬───────────┬─────────────────┬──────────┬─────────┬─────────┐
│ Backend   │ Session       │ Type      │ Model           │ Duration │      RX │      TX │
├───────────┼───────────────┼───────────┼─────────────────┼──────────┼─────────┼─────────┤
│ openai.1  │ abc123def4... │ streaming │ gpt-4           │    12.3s │ 15.0 KB │ 14.5 KB │
│ anthropic │ xyz789abc1... │ streaming │ claude-3-sonnet │     5.7s │  8.2 KB │  8.0 KB │
└───────────┴───────────────┴───────────┴─────────────────┴──────────┴─────────┴─────────┘

Refreshing every 1.0s... (Ctrl+C to stop)
```

## Performance Considerations

Activity tracking is designed for minimal performance impact:

- **Atomic Operations**: Uses `threading.Lock` for thread-safe counter updates
- **O(1) Updates**: Counter increments are simple integer additions
- **Lazy Snapshots**: Snapshot data is copied only when requested
- **No Per-Chunk Logging**: Activity updates don't generate log entries unless DEBUG level is enabled

## Implementation Details

### Connection Types

- `streaming`: Server-Sent Events (SSE) streaming responses
- `non_streaming`: Standard JSON responses

### Byte Counters

- **bytes_rx**: Bytes received from the backend LLM provider
- **bytes_tx**: Bytes transmitted to the client

Note: Byte counters reflect raw data transfer and may differ from token counts.

### Session Isolation

Each connection is uniquely identified by:
- Backend instance name (e.g., `openai.1`)
- Session ID from the request

This prevents double-counting when the same session makes multiple requests.

### Automatic Cleanup

Connections are automatically removed when:
- The request completes (streaming ends or response is sent)
- An error occurs during processing
- The connection times out (configurable, default 5 minutes)

## Troubleshooting

### No Activity Shown

1. Verify the proxy is running and accessible
2. Check that requests are being routed through the proxy
3. Ensure backends are initialized (check `is_functional` in diagnostics)

### Stale Connections

If connections appear stuck:
- Check backend health in `/v1/diagnostics`
- Review proxy logs for connection errors
- The stale connection cleanup runs periodically (5-minute default timeout)

### High Connection Count

A high number of active connections may indicate:
- Slow backend responses
- Client not consuming streams
- Network issues causing request backlog

## Security

The diagnostics endpoint is restricted to localhost access only. Remote access will receive a 403 Forbidden response.

