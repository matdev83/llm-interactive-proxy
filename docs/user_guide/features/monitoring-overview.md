# Monitoring and Analytics Overview

The LLM Interactive Proxy provides comprehensive monitoring and analytics capabilities to help you understand usage patterns, track costs, and optimize performance.

## Available Features

### Usage Tracking and Statistics

**[Usage Tracking and Statistics](usage-tracking.md)** provides detailed monitoring of all traffic passing through the proxy.

**Key Capabilities:**
- Multi-point token tracking (verbatim and mutated)
- Performance metrics (TTFT, latency, throughput)
- Cost tracking and billing reconciliation
- Request/response monitoring
- Tool call tracking
- Multi-dimensional filtering and aggregation

**Use Cases:**
- Billing reconciliation with provider invoices
- Performance monitoring and optimization
- Cost analysis by backend, model, and time period
- Tool usage analysis
- Session and conversation analysis
- Error rate monitoring

**Quick Start:**
```bash
# Get aggregated statistics
curl "http://localhost:8000/v1/usage/stats?backend_type=openai&model=gpt-4"

# Get recent usage records
curl "http://localhost:8000/v1/usage/recent?limit=50"

# Export usage data
curl "http://localhost:8000/v1/usage/export?start_date=2025-12-01T00:00:00Z&end_date=2025-12-31T23:59:59Z"
```

### Replacement Metrics

**[Replacement Metrics](replacement-metrics.md)** tracks activation rates and effectiveness of the [random model replacement](random-model-replacement.md) feature.

**Key Capabilities:**
- Track replacement activation rates
- Monitor turn counts before replacement
- Analyze opt-out patterns
- Measure replacement effectiveness

### Wire Capture

**[Wire Capture](../debugging/wire-capture.md)** records full HTTP requests and responses for debugging.

**Key Capabilities:**
- Record complete request/response cycles
- Analyze traffic patterns
- Debug integration issues
- Replay captured sessions

## Comparison Matrix

| Feature | Token Tracking | Cost Tracking | Performance Metrics | Request Details | Real-time API |
|---------|---------------|---------------|---------------------|-----------------|---------------|
| **Usage Tracking** | ✓ (4 points) | ✓ | ✓ (TTFT, latency) | ✓ (full details) | ✓ |
| **Replacement Metrics** | - | - | - | ✓ (replacements) | ✓ |
| **Wire Capture** | - | - | - | ✓ (full payload) | - |

## Configuration

### Enable All Monitoring Features

```yaml
# Usage tracking (enabled by default)
usage_tracking:
  enabled: true
  persistence_path: "./var/usage_data.json"
  flush_interval_seconds: 30.0

# Wire capture (disabled by default)
wire_capture:
  enabled: true
  output_dir: "./var/wire_captures"
```

### Environment Variables

```bash
# Usage tracking
export USAGE_TRACKING_ENABLED=true
export USAGE_TRACKING_PERSISTENCE_PATH="./var/usage_data.json"

# Wire capture
export WIRE_CAPTURE_ENABLED=true
export WIRE_CAPTURE_OUTPUT_DIR="./var/wire_captures"
```

## Security Considerations

### Default Binding

For security, the proxy binds to `127.0.0.1:8000` (localhost only) by default. This means:
- REST API endpoints are only accessible from the local machine
- External access requires explicit configuration
- Authentication is enforced when binding to external interfaces

To allow external access:

```yaml
# config.yaml
host: "0.0.0.0"  # Bind to all interfaces
auth:
  disable_auth: false  # Keep authentication enabled
```

Or via command line:

```bash
python -m src.core.cli --host 0.0.0.0
```

> **Warning**: When exposing the API externally, always ensure authentication is enabled to prevent unauthorized access to usage data.

## Usage Examples

### Query Aggregated Statistics

```bash
# Get statistics for a specific backend
curl "http://localhost:8000/v1/usage/stats?backend_type=openai"

# Get statistics with multiple filters
curl "http://localhost:8000/v1/usage/stats?backend_type=anthropic&model=claude-3-5-sonnet&start_date=2025-12-01T00:00:00Z"
```

### Export Usage Data

```bash
# Export usage data for a date range
curl "http://localhost:8000/v1/usage/export?start_date=2025-12-01T00:00:00Z&end_date=2025-12-31T23:59:59Z" > usage_data.json
```

### Monitor Performance

```bash
# Check TTFT and latency metrics
curl "http://localhost:8000/v1/usage/stats" | jq '.ttft_stats, .duration_stats'
```

## Use Cases

### 1. Billing Reconciliation

Use **Usage Tracking** to compare proxy-calculated tokens with backend-reported tokens:

```bash
curl "http://localhost:8000/v1/usage/stats?backend_type=openai" | jq '{
  proxy_tokens: .total_tokens,
  backend_tokens: .backend_reported_total_tokens,
  difference: (.total_tokens - .backend_reported_total_tokens)
}'
```

### 2. Performance Monitoring

Track Time to First Token (TTFT) and identify slow responses:

```bash
curl "http://localhost:8000/v1/usage/stats" | jq '.ttft_stats'
```

### 3. Cost Analysis

Analyze costs by backend and model:

```bash
curl "http://localhost:8000/v1/usage/stats?backend_type=anthropic" | jq '{
  total_cost: .total_cost,
  requests: .request_count,
  cost_per_request: (.total_cost / .request_count)
}'
```

### 4. Debugging Integration Issues

Use **Wire Capture** to record and analyze problematic requests:

```bash
# Enable wire capture
python -m src.core.cli --wire-capture-enabled

# Analyze captured traffic
python scripts/inspect_cbor_capture.py var/wire_captures_cbor/capture_file.cbor --detect-issues
```

### 5. Model Replacement Analysis

Track replacement effectiveness with **Replacement Metrics**:

```bash
curl "http://localhost:8000/v1/replacement/metrics"
```

## Best Practices

### 1. Regular Monitoring

Set up automated monitoring to track key metrics:
- Token consumption trends
- Error rates (HTTP status codes)
- Performance degradation (TTFT increases)
- Cost anomalies

### 2. Data Retention

Configure appropriate retention policies:
```yaml
usage_tracking:
  max_records_in_memory: 100000  # Adjust based on traffic volume
  flush_interval_seconds: 30.0   # Balance between durability and performance
```

### 3. Privacy Considerations

Usage tracking does NOT record:
- Message content (prompts or completions)
- API keys or authentication tokens
- Personal identifiable information (PII)

### 4. Performance Impact

All monitoring features are designed for minimal overhead:
- Usage tracking: <1ms per request
- Wire capture: ~2-5ms per request (when enabled)
- Replacement metrics: <0.1ms per request

## Troubleshooting

### High Memory Usage

If usage tracking consumes too much memory:
1. Reduce `max_records_in_memory`
2. Increase `flush_interval_seconds`
3. Implement custom archival logic

### Missing Data

If usage data is missing after restart:
1. Check `persistence_path` is writable
2. Verify file exists at configured path
3. Check proxy logs for persistence errors

### Slow Queries

If statistics queries are slow:
1. Add more specific filters to reduce result set
2. Use date range filters to limit scope
3. Consider implementing database persistence for large deployments

## Related Documentation

- **[Usage Tracking User Guide](usage-tracking.md)** - Complete feature documentation
- **[Usage Tracking Integration Guide](../../../docs/usage-tracking-integration.md)** - Developer integration guide
- **[Wire Capture Guide](../debugging/wire-capture.md)** - Traffic recording and analysis
- **[Replacement Metrics Guide](replacement-metrics.md)** - Model replacement tracking
- **[Configuration Guide](../configuration.md)** - Complete configuration reference

## See Also

- [Debugging Guide](../debugging/troubleshooting.md)
- [Performance Tuning](../performance-tuning.md)
- [Security Best Practices](../security/authentication.md)
