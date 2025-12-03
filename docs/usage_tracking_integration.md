# Usage Tracking Integration Guide

This document describes the usage tracking infrastructure for developers who need to integrate usage tracking into custom controllers, middleware, or backend connectors.

> **For end-users**: See the [Usage Tracking User Guide](user_guide/features/usage-tracking.md) for configuration, API usage, and monitoring.

## Overview

The usage tracking system provides comprehensive monitoring of all traffic passing through the proxy, enabling detailed analysis, billing reconciliation, and performance monitoring. The system tracks usage at four measurement points to provide full observability of both verbatim (original) and mutated (modified) traffic.

This guide covers:
- Service architecture and dependency injection
- Integration patterns for controllers and middleware
- Helper functions for common use cases
- Testing strategies
- Performance considerations

## Components

### 1. Configuration (AppConfig)

Usage tracking is configured through the `UsageTrackingConfig` class in `AppConfig`:

```python
from src.core.config.app_config import AppConfig

config = AppConfig.from_env()

# Access usage tracking configuration
print(config.usage_tracking.enabled)  # True by default
print(config.usage_tracking.persistence_path)  # "./var/usage_data.json"
print(config.usage_tracking.flush_interval_seconds)  # 30.0
print(config.usage_tracking.max_records_in_memory)  # 100000
```

Configuration options:
- `enabled`: Whether detailed usage tracking is enabled (default: True)
- `persistence_path`: Path for persistence file (default: "./var/usage_data.json")
- `flush_interval_seconds`: Interval for periodic persistence (default: 30.0)
- `max_records_in_memory`: Maximum records to keep in memory (default: 100000)

### 2. Services

Three main services are registered in the DI container:

#### InMemoryUsageStore
Thread-safe storage with periodic persistence to disk.

```python
from src.core.services.in_memory_usage_store import InMemoryUsageStore

store = service_provider.get_required_service(InMemoryUsageStore)
```

#### UsageRecordingService
Service for recording usage metrics at request/response boundaries.

```python
from src.core.interfaces.usage_recording_interface import IUsageRecordingService

usage_service = service_provider.get_required_service(IUsageRecordingService)

# Record a request
record_id = await usage_service.record_request(
    session_id="session-123",
    backend_type="openai",
    model="gpt-4",
    frontend_type="openai",
    leg=TrafficLeg.CLIENT_TO_PROXY,
    prompt_tokens=100,
    user_agent="MyApp/1.0",
    proxy_user="user@example.com",
)

# Complete the record with response data
await usage_service.record_response(
    record_id=record_id,
    completion_tokens=50,
    http_status_code=200,
    tool_call_count=2,
    tool_names=["search", "calculate"],
    ttft_ms=150.0,
    proxy_processing_ms=10.0,
    total_duration_ms=500.0,
)
```

#### StatisticsAggregationService
Service for aggregating usage statistics with filtering.

```python
from src.core.interfaces.statistics_service_interface import IStatisticsService
from src.core.domain.statistics_filter import StatisticsFilter

stats_service = service_provider.get_required_service(IStatisticsService)

# Get aggregated statistics
filter = StatisticsFilter(backend_type="openai", model="gpt-4")
stats = await stats_service.get_aggregated_stats(filter)

print(f"Total requests: {stats.request_count}")
print(f"Total tokens: {stats.total_tokens}")
print(f"Tokens per session: {stats.tokens_per_session}")
```

### 3. Middleware

The `UsageTrackingMiddleware` captures timing and user context at the request/response boundaries:

```python
from src.core.app.middleware.usage_tracking_middleware import UsageTrackingMiddleware

# Middleware is automatically registered when usage_tracking.enabled = True
# It captures:
# - Request start time
# - User-agent header
# - Proxy user header
# - Response end time
# - Total duration
```

The middleware stores timing information in `request.state` for downstream use:
- `request.state.request_start_time`: Request start timestamp
- `request.state.user_agent`: User-agent string
- `request.state.proxy_user`: Proxy user identifier
- `request.state.response_end_time`: Response end timestamp
- `request.state.total_duration_ms`: Total request duration in milliseconds

### 4. Helper Functions

Helper functions are provided for controllers to record usage:

```python
from src.core.app.helpers.usage_recording_helper import (
    record_request_usage,
    record_response_usage,
    extract_tool_calls_from_response,
    extract_backend_reported_usage,
)

# In a controller:
async def handle_request(request: Request, ...):
    # Record request
    record_id = await record_request_usage(
        usage_service=usage_service,
        request=request,
        session_id=session_id,
        backend_type="openai",
        model="gpt-4",
        frontend_type="openai",
        leg=TrafficLeg.CLIENT_TO_PROXY,
        prompt_tokens=100,
    )
    
    # Process request...
    response = await process_request(...)
    
    # Extract tool calls and backend usage
    tool_call_count, tool_names = extract_tool_calls_from_response(response)
    backend_usage = extract_backend_reported_usage(response)
    
    # Record response
    await record_response_usage(
        usage_service=usage_service,
        request=request,
        record_id=record_id,
        completion_tokens=50,
        http_status_code=200,
        tool_call_count=tool_call_count,
        tool_names=tool_names,
        backend_reported_usage=backend_usage,
    )
```

## Usage Tracking Points

The system tracks usage at four measurement points:

1. **CLIENT_TO_PROXY (CTP)**: Verbatim tokens from client request before proxy modifications
2. **PROXY_TO_BACKEND (PTB)**: Mutated tokens sent to backend after proxy modifications
3. **BACKEND_TO_PROXY (BTP)**: Verbatim tokens from backend response before proxy modifications
4. **PROXY_TO_CLIENT (PTC)**: Mutated tokens sent to client after proxy modifications

Additionally, backend-reported usage is captured separately for reconciliation.

## REST API Endpoints

Usage statistics can be queried via REST API endpoints (implemented in `src/core/app/routes/usage_routes.py`):

- `GET /v1/usage/stats`: Get aggregated statistics with filtering
- `GET /v1/usage/recent`: Get recent usage records
- `GET /v1/usage/export`: Export usage data as JSON

## Integration with Controllers

To integrate usage tracking in a controller:

1. Resolve the `IUsageRecordingService` from the DI container
2. Use the helper functions to record request/response usage
3. Extract tool calls and backend-reported usage from responses
4. Record timing information from `request.state`

Example:

```python
from src.core.app.helpers.usage_recording_helper import (
    record_request_usage,
    record_response_usage,
)
from src.core.domain.traffic_leg import TrafficLeg
from src.core.interfaces.usage_recording_interface import IUsageRecordingService

class MyController:
    def __init__(self, usage_service: IUsageRecordingService):
        self._usage_service = usage_service
    
    async def handle_chat_completion(self, request: Request, ...):
        # Record request
        record_id = await record_request_usage(
            usage_service=self._usage_service,
            request=request,
            session_id=session_id,
            backend_type=backend_type,
            model=model,
            frontend_type="openai",
            leg=TrafficLeg.CLIENT_TO_PROXY,
            prompt_tokens=prompt_tokens,
        )
        
        # Process request...
        response = await self._process_request(...)
        
        # Record response
        await record_response_usage(
            usage_service=self._usage_service,
            request=request,
            record_id=record_id,
            completion_tokens=completion_tokens,
            http_status_code=200,
        )
        
        return response
```

## Testing

The usage tracking infrastructure includes comprehensive tests:

- **Property-based tests**: `tests/property/test_usage_tracking_domain_properties.py`
- **Service tests**: `tests/property/test_usage_recording_service_properties.py`
- **Integration tests**: `tests/integration/test_usage_tracking_integration.py`
- **Unit tests**: `tests/unit/test_statistics_aggregation_service.py`

Run all tests:
```bash
./.venv/Scripts/python.exe -m pytest tests/property/test_usage_tracking_domain_properties.py -v
./.venv/Scripts/python.exe -m pytest tests/integration/test_usage_tracking_integration.py -v
```

## Disabling Usage Tracking

To disable usage tracking, set `enabled: false` in the configuration:

```yaml
usage_tracking:
  enabled: false
```

Or via environment variable:
```bash
export USAGE_TRACKING_ENABLED=false
```

When disabled, the services will not be registered in the DI container, and the middleware will not be added to the application.

## Performance Considerations

### Memory Usage

The in-memory store keeps up to `max_records_in_memory` records (default: 100,000). Each record is approximately 1-2 KB, so the default configuration uses ~100-200 MB of memory.

To reduce memory usage:
- Decrease `max_records_in_memory`
- Increase `flush_interval_seconds` to persist more frequently
- Implement custom archival logic for old records

### Thread Safety

All usage tracking services are thread-safe:
- `InMemoryUsageStore` uses `threading.RLock` for concurrent access
- Services can be safely called from multiple request handlers
- No external locking is required when using the services

### Performance Impact

Usage tracking adds minimal overhead:
- Request recording: <1ms per request
- Response recording: <1ms per response
- Statistics aggregation: <10ms for typical queries
- Persistence: Asynchronous, does not block request handling

## Best Practices

### 1. Use Helper Functions

Always use the helper functions instead of calling services directly:

```python
# Good
await record_request_usage(usage_service, request, ...)

# Avoid
record_id = await usage_service.record_request(...)
```

### 2. Extract Backend Usage

Always extract and record backend-reported usage for reconciliation:

```python
backend_usage = extract_backend_reported_usage(response)
await record_response_usage(
    usage_service=usage_service,
    record_id=record_id,
    backend_reported_usage=backend_usage,
    ...
)
```

### 3. Handle Errors Gracefully

Usage tracking should never break request processing:

```python
try:
    await record_request_usage(...)
except Exception as e:
    logger.error(f"Failed to record usage: {e}")
    # Continue processing request
```

### 4. Test Integration

Always test usage tracking integration:

```python
async def test_controller_records_usage(usage_service_mock):
    controller = MyController(usage_service=usage_service_mock)
    await controller.handle_request(...)
    
    # Verify usage was recorded
    usage_service_mock.record_request.assert_called_once()
    usage_service_mock.record_response.assert_called_once()
```

## Troubleshooting

### Usage Not Being Recorded

1. Check that `usage_tracking.enabled = true` in configuration
2. Verify services are registered in DI container
3. Check logs for errors during service initialization
4. Ensure helper functions are being called in controllers

### Incorrect Token Counts

1. Verify tokenization is using the correct model
2. Check that verbatim/mutated tokens are captured at correct points
3. Compare proxy-calculated vs backend-reported tokens
4. Review token extraction logic in helper functions

### High Memory Usage

1. Check `max_records_in_memory` configuration
2. Monitor record count with `len(store._records)`
3. Implement custom archival for old records
4. Consider using SQLite persistence for large deployments

## References

- **User Guide**: [Usage Tracking and Statistics](user_guide/features/usage-tracking.md)
- **Design Document**: `.kiro/specs/detailed-usage-tracking/design.md`
- **Requirements Document**: `.kiro/specs/detailed-usage-tracking/requirements.md`
- **API Routes**: `src/core/app/routes/usage_routes.py`
- **Services**: `src/core/services/usage_recording_service.py`, `src/core/services/statistics_aggregation_service.py`
- **Domain Models**: `src/core/domain/usage_record.py`, `src/core/domain/traffic_leg.py`
