# Usage Tracking and Statistics

The LLM Interactive Proxy includes a comprehensive usage tracking system that monitors all traffic passing through the proxy. This feature provides detailed insights into token consumption, request patterns, performance metrics, and costs across all backends and models.

## Overview

The usage tracking system captures metrics at four measurement points to provide complete visibility into both original (verbatim) and modified (mutated) traffic:

1. **Client to Proxy (CTP)**: Original request from client before any proxy modifications
2. **Proxy to Backend (PTB)**: Modified request sent to backend after proxy transformations
3. **Backend to Proxy (BTP)**: Original response from backend before proxy modifications
4. **Proxy to Client (PTC)**: Modified response sent to client after proxy transformations

This multi-point tracking enables you to:
- Compare what clients send vs. what backends receive (mutation impact on prompts)
- Compare what backends return vs. what clients receive (mutation impact on responses)
- Reconcile proxy calculations with backend billing (proxy vs. backend-reported usage)

## Key Features

### Token Tracking
- **Verbatim tokens**: Original token counts before proxy modifications
- **Mutated tokens**: Token counts after proxy transformations (command injection, content filtering, etc.)
- **Backend-reported tokens**: Token counts reported by the LLM provider for billing reconciliation
- **Extended token details**: Reasoning tokens (thinking models), cached tokens, audio tokens

### Request Monitoring
- Request and response counts per backend, model, and frontend
- HTTP status code tracking and error rate monitoring
- Tool call tracking with tool names and counts
- Session and turn tracking for conversation analysis

### Performance Metrics
- Time to First Token (TTFT) for streaming responses
- Proxy processing time (overhead measurement)
- Total request duration
- Statistical aggregations: min, max, average, p50, p95, p99

### Cost Tracking
- Backend-reported costs per request (when available)
- Upstream inference costs for BYOK (Bring Your Own Key) scenarios
- Cost aggregation by backend, model, session, and time period

### Multi-Dimensional Analysis
Filter and aggregate statistics by:
- Backend type (openai, anthropic, gemini, etc.)
- Model name
- Frontend type (OpenAI API, Anthropic API, etc.)
- Traffic leg (CTP, PTB, BTP, PTC)
- User agent or application
- Proxy user
- Date and time dimensions (day, week, month, hour of day)

## Configuration

Usage tracking is enabled by default. Configure it in your `config.yaml`:

```yaml
usage_tracking:
  enabled: true
  persistence_path: "./var/usage_data.json"
  flush_interval_seconds: 30.0
  max_records_in_memory: 100000
```

### Configuration Options

- **enabled**: Enable or disable usage tracking (default: `true`)
- **persistence_path**: Path to store usage data (default: `"./var/usage_data.json"`)
- **flush_interval_seconds**: How often to persist data to disk (default: `30.0`)
- **max_records_in_memory**: Maximum records to keep in memory before archival (default: `100000`)

### Environment Variables

You can also configure via environment variables:

```bash
export USAGE_TRACKING_ENABLED=true
export USAGE_TRACKING_PERSISTENCE_PATH="./var/usage_data.json"
export USAGE_TRACKING_FLUSH_INTERVAL_SECONDS=30.0
export USAGE_TRACKING_MAX_RECORDS_IN_MEMORY=100000
```

## REST API Endpoints

Query usage statistics via REST API.

> **Security Note**: By default, the proxy binds to `127.0.0.1:8000` (localhost only) for security. To allow external access, explicitly configure the host with `--host 0.0.0.0` or set `host: "0.0.0.0"` in your configuration file. When exposing the API externally, ensure proper authentication is enabled.

### Get Aggregated Statistics

```bash
GET /v1/usage/stats
```

Query parameters:
- `backend_type`: Filter by backend (e.g., `openai`, `anthropic`)
- `model`: Filter by model name (e.g., `gpt-4`, `claude-3-5-sonnet`)
- `frontend_type`: Filter by frontend API type
- `leg`: Filter by traffic leg (`CTP`, `PTB`, `BTP`, `PTC`)
- `user_agent`: Filter by user agent string
- `proxy_user`: Filter by proxy user identifier
- `start_date`: Start of date range (ISO 8601 format)
- `end_date`: End of date range (ISO 8601 format)
- `hour_of_day`: Filter by hour (0-23)
- `day_of_week`: Filter by day (0=Monday, 6=Sunday)

Example:

```bash
# Get stats for OpenAI GPT-4 in the last 24 hours
curl "http://localhost:8000/v1/usage/stats?backend_type=openai&model=gpt-4&start_date=2025-12-02T00:00:00Z"
```

Response:

```json
{
  "request_count": 150,
  "response_count": 148,
  "unique_sessions": 12,
  "total_turns": 150,
  "total_prompt_tokens": 45000,
  "total_completion_tokens": 15000,
  "total_tokens": 60000,
  "tokens_per_session": 5000.0,
  "completion_tokens_per_second": 2.5,
  "total_tokens_per_second": 10.0,
  "total_tool_calls": 45,
  "ttft_stats": {
    "count": 148,
    "min_ms": 120.5,
    "max_ms": 2500.0,
    "avg_ms": 450.2,
    "p50_ms": 380.0,
    "p95_ms": 1200.0,
    "p99_ms": 2000.0
  },
  "proxy_processing_stats": {
    "count": 148,
    "min_ms": 5.2,
    "max_ms": 50.0,
    "avg_ms": 12.5,
    "p50_ms": 10.0,
    "p95_ms": 25.0,
    "p99_ms": 40.0
  },
  "duration_stats": {
    "count": 148,
    "min_ms": 500.0,
    "max_ms": 15000.0,
    "avg_ms": 3500.0,
    "p50_ms": 3000.0,
    "p95_ms": 8000.0,
    "p99_ms": 12000.0
  },
  "status_code_counts": {
    "200": 148,
    "429": 2
  },
  "filters": {
    "backend_type": "openai",
    "model": "gpt-4"
  },
  "time_window_seconds": 86400.0
}
```

### Get Recent Usage Records

```bash
GET /v1/usage/recent
```

Query parameters:
- `limit`: Maximum number of records to return (default: 100, max: 1000)
- `session_id`: Filter by session ID
- All filter parameters from `/v1/usage/stats`

Example:

```bash
# Get last 50 usage records for a specific session
curl "http://localhost:8000/v1/usage/recent?session_id=session-123&limit=50"
```

### Export Usage Data

```bash
GET /v1/usage/export
```

Query parameters:
- `start_date`: Start of date range (required)
- `end_date`: End of date range (required)
- All filter parameters from `/v1/usage/stats`

Example:

```bash
# Export all usage data for December 2025
curl "http://localhost:8000/v1/usage/export?start_date=2025-12-01T00:00:00Z&end_date=2025-12-31T23:59:59Z" > usage_december.json
```

## Use Cases

### Billing Reconciliation

Compare proxy-calculated tokens with backend-reported tokens to identify discrepancies:

```bash
# Get stats with backend-reported usage
curl "http://localhost:8000/v1/usage/stats?backend_type=openai&model=gpt-4"
```

The response includes both proxy-calculated tokens and backend-reported usage for comparison.

### Performance Monitoring

Track Time to First Token (TTFT) and identify slow responses:

```bash
# Get stats for the last hour
curl "http://localhost:8000/v1/usage/stats?start_date=$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)"
```

Check the `ttft_stats` section for percentile breakdowns.

### Cost Analysis

Analyze costs by backend, model, and time period:

```bash
# Get stats for Anthropic Claude models
curl "http://localhost:8000/v1/usage/stats?backend_type=anthropic"
```

Backend-reported costs are included when available from the provider.

### Tool Usage Analysis

Track which tools are being called and how often:

```bash
# Get recent records with tool calls
curl "http://localhost:8000/v1/usage/recent?limit=100" | jq '.records[] | select(.tool_call_count > 0)'
```

### Session Analysis

Analyze token consumption per session:

```bash
# Get stats for a specific session
curl "http://localhost:8000/v1/usage/stats?session_id=session-123"
```

Check `tokens_per_session` for average consumption.

### Error Rate Monitoring

Track HTTP status codes to identify issues:

```bash
# Get status code breakdown
curl "http://localhost:8000/v1/usage/stats" | jq '.status_code_counts'
```

## Data Persistence

Usage data is stored in memory for fast access and periodically persisted to disk:

- **In-memory storage**: Thread-safe data structure for low-latency recording
- **Periodic persistence**: Data is flushed to disk every 30 seconds (configurable)
- **Startup recovery**: Previously persisted data is loaded on proxy startup
- **Graceful shutdown**: Data is persisted when the proxy shuts down

### Storage Location

By default, usage data is stored at `./var/usage_data.json`. This file contains:

```json
{
  "version": 1,
  "last_flush": "2025-12-03T10:30:00Z",
  "records": [...],
  "sessions": [...],
  "aggregated_stats": {...}
}
```

### Data Retention

Configure `max_records_in_memory` to control how many records are kept in memory. When this limit is reached, older records are archived or removed based on your retention policy.

## Privacy and Security

### Sensitive Data

Usage records do NOT include:
- Message content (prompts or completions)
- API keys or authentication tokens
- Personal identifiable information (PII)

Usage records DO include:
- Token counts and timing metrics
- Model and backend identifiers
- Session IDs and turn numbers
- User agent and proxy user (if provided)
- Tool names (but not tool arguments)

### Access Control

The usage API endpoints are protected by the same authentication mechanism as the main proxy API. Ensure proper API key authentication is configured.

## Disabling Usage Tracking

To disable usage tracking entirely:

```yaml
usage_tracking:
  enabled: false
```

Or via environment variable:

```bash
export USAGE_TRACKING_ENABLED=false
```

When disabled:
- No usage data is recorded
- API endpoints return empty results
- No performance overhead from tracking

## Troubleshooting

### High Memory Usage

If memory usage is high, reduce `max_records_in_memory`:

```yaml
usage_tracking:
  max_records_in_memory: 50000
```

### Slow Persistence

If disk writes are slow, increase `flush_interval_seconds`:

```yaml
usage_tracking:
  flush_interval_seconds: 60.0
```

### Missing Data

If usage data is missing after restart:
1. Check that `persistence_path` is writable
2. Verify the file exists at the configured path
3. Check proxy logs for persistence errors

## Related Features

- **[Wire Capture](../debugging/wire-capture.md)**: Record full HTTP requests/responses for debugging
- **[Replacement Metrics](replacement-metrics.md)**: Track model replacement activation rates
- **[Session Management](session-management.md)**: Intelligent session handling and state management

## Developer Integration

For developers integrating usage tracking into custom controllers or middleware, see the [Usage Tracking Integration Guide](../../../docs/usage_tracking_integration.md).

## See Also

- [Configuration Guide](../configuration.md)
- [REST API Reference](../api-reference.md)
- [Debugging Guide](../debugging/troubleshooting.md)
