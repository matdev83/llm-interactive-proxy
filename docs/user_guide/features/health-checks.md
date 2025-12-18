# Backend Health Checks and Circuit Breaker

The LLM Interactive Proxy includes a comprehensive health monitoring system that automatically detects unhealthy backend API endpoints and excludes them from request routing.

## Overview

The health check system provides:

- **ICMP Ping Checks** - Network-level reachability monitoring
- **HTTP Probe Checks** - Application-level health verification  
- **Circuit Breaker** - Automatic exclusion of unhealthy backends from routing
- **Backend Notifications** - Real-time health state updates to backend instances
- **Health API** - REST endpoint for monitoring health status

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Health Check System                          │
│                                                                 │
│  ┌─────────────────┐     ┌─────────────────┐                   │
│  │ ICMPHealthChecker│     │ HTTPHealthChecker│                   │
│  │   (ping)         │     │   (HTTP probe)   │                   │
│  └────────┬────────┘     └────────┬────────┘                   │
│           │                       │                             │
│           └───────────┬───────────┘                             │
│                       ▼                                         │
│           ┌───────────────────────┐                             │
│           │  HealthStateManager   │  Tracks state per URL       │
│           └───────────┬───────────┘                             │
│                       │                                         │
│                       ▼  EndpointHealthChanged event            │
│           ┌───────────────────────┐                             │
│           │ BackendHealthNotifier │  Notifies backend instances │
│           └───────────┬───────────┘                             │
│                       │                                         │
│         ┌─────────────┼─────────────┐                           │
│         ▼             ▼             ▼                           │
│    [Backend 1]   [Backend 2]   [Backend 3]                      │
│    unhealthy     unhealthy     healthy                          │
└─────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Request Routing                              │
│                                                                 │
│  BackendService._filter_unhealthy_backends()                    │
│  → Excludes backends where is_backend_functional() = False      │
│  → Circuit breaker prevents requests to unhealthy endpoints     │
└─────────────────────────────────────────────────────────────────┘
```

## Configuration

### YAML Configuration

```yaml
health_check:
  # Master switch for the health check system
  enabled: true
  
  # Circuit breaker - exclude unhealthy backends from routing
  circuit_breaker_enabled: true
  
  # Notify backend instances of health changes
  notify_backends: true
  
  # Log successful health checks (verbose)
  log_healthy_checks: false
  
  # Ping (ICMP) check settings
  ping:
    enabled: true
    interval_seconds: 30.0
    timeout_seconds: 5.0
    failure_threshold: 3  # Consecutive failures before marking unhealthy
  
  # HTTP probe settings
  http:
    enabled: true
    interval_seconds: 60.0
    timeout_seconds: 10.0
    failure_threshold: 2  # Consecutive failures before marking unhealthy
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `true` | Enable the health check system |
| `circuit_breaker_enabled` | bool | `true` | Exclude unhealthy backends from routing |
| `notify_backends` | bool | `true` | Notify backend instances of health changes |
| `log_healthy_checks` | bool | `false` | Log successful checks (can be verbose) |
| `ping.enabled` | bool | `true` | Enable ICMP ping checks |
| `ping.interval_seconds` | float | `30.0` | Seconds between ping checks |
| `ping.timeout_seconds` | float | `5.0` | Ping timeout |
| `ping.failure_threshold` | int | `3` | Consecutive failures before unhealthy |
| `http.enabled` | bool | `true` | Enable HTTP probe checks |
| `http.interval_seconds` | float | `60.0` | Seconds between HTTP checks |
| `http.timeout_seconds` | float | `10.0` | HTTP request timeout |
| `http.failure_threshold` | int | `2` | Consecutive failures before unhealthy |

## How It Works

### 1. Endpoint Registration

When a backend is created, its API URL is automatically registered for health monitoring:

```
Backend "openai.1" created → API URL "https://api.openai.com/v1" registered
Backend "openai.2" created → Same URL, both backends share health state
```

### 2. Health Checks

The system performs two types of checks on each unique API URL:

**ICMP Ping Check:**
- Verifies network reachability
- Low overhead, fast detection of network issues
- Runs every 30 seconds by default

**HTTP Probe Check:**
- Verifies the API endpoint is responding
- Sends HEAD request to the API base URL
- Runs every 60 seconds by default

### 3. State Transitions

Health state transitions follow these rules:

| Current State | Event | New State | Action |
|--------------|-------|-----------|--------|
| Healthy | Ping fails (< threshold) | Healthy | Increment failure counter |
| Healthy | Ping fails (≥ threshold) | **Unhealthy** | Notify backends, log WARNING |
| Unhealthy | Ping succeeds | **Healthy** | Notify backends, log WARNING |
| Healthy | HTTP fails (< threshold) | Healthy | Increment failure counter |
| Healthy | HTTP fails (≥ threshold) | **Unhealthy** | Notify backends, log WARNING |
| Unhealthy | HTTP succeeds | **Healthy** | Notify backends, log WARNING |

### 4. Circuit Breaker

When `circuit_breaker_enabled: true`, the routing logic automatically excludes unhealthy backends:

```python
# Before routing, unhealthy backends are filtered out
Original plan: [("openai.1", "gpt-4"), ("openai.2", "gpt-4"), ("anthropic.1", "claude-3")]
                    ↓ openai.1 and openai.2 share unhealthy URL
Filtered plan: [("anthropic.1", "claude-3")]
```

**Safety Fallback:** If ALL backends would be filtered out, the original plan is used to prevent complete service failure.

### 5. Backend Notifications

Backend instances receive real-time notifications when their API URL's health changes:

```python
# When URL becomes unhealthy:
backend.on_endpoint_unhealthy("https://api.openai.com/v1", "ping failed: timeout")
backend._endpoint_healthy = False

# When URL recovers:
backend.on_endpoint_healthy("https://api.openai.com/v1")
backend._endpoint_healthy = True
```

## Monitoring Health Status

### REST API Endpoint

Query the `/internal/health` endpoint to get health status:

```bash
curl http://localhost:8000/internal/health | jq '.endpoint_health'
```

Response:

```json
{
  "endpoint_health": {
    "enabled": true,
    "summary": {
      "total_endpoints": 2,
      "healthy_endpoints": 1,
      "unhealthy_endpoints": 1
    },
    "endpoints": [
      {
        "api_url": "https://api.openai.com/v1",
        "is_healthy": false,
        "ping_check_success": false,
        "http_check_success": true,
        "last_ping_check_timestamp": "2025-12-05T12:00:00+00:00",
        "last_http_check_timestamp": "2025-12-05T12:00:30+00:00",
        "consecutive_ping_failures": 3,
        "consecutive_http_failures": 0,
        "last_ping_latency_ms": null,
        "last_http_latency_ms": 150.5,
        "last_http_status_code": 200,
        "last_ping_error": "Request timed out",
        "last_http_error": null,
        "backends_using_url": ["openai.1", "openai.2"]
      },
      {
        "api_url": "https://api.anthropic.com",
        "is_healthy": true,
        "ping_check_success": true,
        "http_check_success": true,
        "backends_using_url": ["anthropic.1"]
      }
    ],
    "backends": [
      {
        "api_url": "https://api.openai.com/v1",
        "backend_type": "openai",
        "is_endpoint_healthy": false
      },
      {
        "api_url": "https://api.anthropic.com",
        "backend_type": "anthropic",
        "is_endpoint_healthy": true
      }
    ]
  }
}
```

### Demo Script

Use the included demo script to query health status:

```bash
# Human-readable format
.venv/Scripts/python.exe scripts/demo_health_api.py

# Raw JSON output
.venv/Scripts/python.exe scripts/demo_health_api.py --raw

# Query different proxy URL
.venv/Scripts/python.exe scripts/demo_health_api.py http://localhost:9000
```

## Logging

Health state transitions are logged at WARNING level:

```
WARNING - Endpoint https://api.openai.com/v1 ping check: healthy → unhealthy (3 consecutive failures)
WARNING - Endpoint https://api.openai.com/v1 HTTP check: unhealthy → healthy
WARNING - Backend 'openai.1' endpoint 'https://api.openai.com/v1' is now unhealthy. Reason: ping failed
INFO - Backend 'openai.1' endpoint 'https://api.openai.com/v1' is now healthy.
```

Routing decisions are also logged:

```
INFO - Skipping backend openai.1 (unhealthy endpoint) in failover plan
WARNING - All backends filtered as unhealthy, falling back to original plan
```

## Use Cases

### 1. Automatic Failover

When a backend API becomes unreachable, traffic automatically routes to healthy alternatives:

```yaml
# Config with multiple OpenAI-compatible backends
backends:
  openai.primary:
    type: openai
    api_key: ${OPENAI_API_KEY}
    api_url: https://api.openai.com/v1
  
  openai.backup:
    type: openai
    api_key: ${OPENAI_BACKUP_KEY}
    api_url: https://backup-api.example.com/v1

failover_routes:
  gpt-4:
    - ["openai.primary", "gpt-4"]
    - ["openai.backup", "gpt-4"]  # Used when primary is unhealthy
```

### 2. Multi-Region Deployments

Health checks enable intelligent routing across regions:

```yaml
backends:
  openai.us:
    type: openai
    api_url: https://us.api.openai.com/v1
  
  openai.eu:
    type: openai
    api_url: https://eu.api.openai.com/v1

# Requests automatically route to healthy region
```

### 3. Monitoring Dashboard Integration

Query the health API for dashboard integration:

```bash
# Check overall health
curl -s http://localhost:8000/internal/health | \
  jq '.endpoint_health.summary.unhealthy_endpoints'

# Alert if any endpoints unhealthy
if [ $(curl -s http://localhost:8000/internal/health | \
       jq '.endpoint_health.summary.unhealthy_endpoints') -gt 0 ]; then
  echo "ALERT: Unhealthy endpoints detected!"
fi
```

## Troubleshooting

### Ping Checks Failing

**Symptoms:** Ping checks fail but HTTP checks succeed.

**Possible Causes:**
1. ICMP blocked by firewall
2. Cloud providers often block ping (AWS, GCP, Azure)

**Solution:** Disable ping checks if not needed:

```yaml
health_check:
  ping:
    enabled: false
```

### All Backends Marked Unhealthy

**Symptoms:** Log shows "All backends filtered as unhealthy, falling back to original plan"

**Possible Causes:**
1. Network connectivity issue
2. Thresholds too aggressive

**Solution:** Adjust thresholds or check network:

```yaml
health_check:
  ping:
    failure_threshold: 5  # More tolerance
  http:
    failure_threshold: 3  # More tolerance
```

### High CPU from Health Checks

**Symptoms:** CPU usage spikes correlate with health check intervals.

**Solution:** Increase intervals:

```yaml
health_check:
  ping:
    interval_seconds: 60.0  # Less frequent
  http:
    interval_seconds: 120.0  # Less frequent
```

### Circuit Breaker Not Working

**Symptoms:** Requests still go to unhealthy backends.

**Check:**
1. Verify `circuit_breaker_enabled: true` in config
2. Check logs for "Skipping backend" messages
3. Query `/internal/health` to verify health state

## Related Documentation

- [Configuration Guide](../configuration.md) - Complete configuration reference
- [Monitoring Overview](monitoring-overview.md) - All monitoring features
- [Troubleshooting Guide](../debugging/troubleshooting.md) - Debugging issues
- [Backend Configuration](../backends/overview.md) - Backend setup

## See Also

- [Failover Configuration](../backends/overview.md#failover-routes) - Configure failover routes
- [Request Deduplication](request-deduplication.md) - Prevent duplicate requests from exhausting rate limits
- [Failure Handling](failure-handling.md) - Automatic retry and failover behavior
- [Usage Tracking](usage-tracking.md) - Monitor request metrics
- [Wire Capture](../debugging/wire-capture.md) - Debug request/response issues












