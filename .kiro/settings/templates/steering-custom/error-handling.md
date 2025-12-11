# Error Handling Standards

[Purpose: unify how errors are classified, shaped, propagated, logged, and monitored]

## Philosophy
- **Fail fast at boundaries** - Validate early, fail with clear messages
- **Degrade gracefully** - Use circuit breakers and fallbacks for external dependencies
- **Consistent error shape** - Structured responses across all APIs
- **Handle known errors close to source** - Surface unknowns to global handler

## Error Hierarchy

All errors extend `LLMProxyError` from `src/core/common/exceptions.py`.

```python
LLMProxyError (base)
├── ValidationError (400)
├── AuthenticationError (401)
├── RoutingError (403)
├── RateLimitExceededError (429)
├── BackendError (502)
│   ├── APIConnectionError
│   └── APITimeoutError
├── ServiceUnavailableError (503)
└── ...
```

## Classification (decide handling by source)

| Category | Examples | HTTP Status | Recovery Strategy |
|----------|----------|-------------|-------------------|
| **Client** | Invalid input, malformed JSON | 400 | Reject with validation errors |
| **Authentication** | Missing/invalid API key | 401 | Reject with auth guidance |
| **Authorization** | Routing policy violation | 403 | Reject with reason |
| **Rate Limiting** | Quota exceeded | 429 | Return Retry-After header |
| **Backend** | Upstream API failure | 502 | Failover to next backend |
| **Server** | Internal service crash | 500 | Log and return generic error |
| **Service Unavailable** | All backends down | 503 | Return retry guidance |

## Error Shape (canonical format)

```python
{
  "error": {
    "type": "BackendError",
    "message": "Backend request failed: timeout",
    "details": {
      "backend_name": "openai",
      "request_id": "req-abc123"
    }
  }
}
```

**Principles**:
- Stable error types for client detection
- Human-readable messages
- No secrets in responses
- Include request ID for tracing

## Propagation (where to convert)

### Service Layer
Throw typed exceptions extending `LLMProxyError`:
```python
async def route_request(self, request):
    if not self.backends:
        raise ServiceUnavailableError(
            "No backends available",
            details={"available_count": 0}
        )
```

### Controller Layer
Convert to HTTP responses:
```python
try:
    result = await backend_service.route_request(request)
    return JSONResponse(result.to_dict())
except LLMProxyError as e:
    return JSONResponse(
        status_code=e.status_code,
        content=e.to_dict()
    )
```

### Global Exception Handler
Catch unexpected errors:
```python
@app.exception_handler(Exception)
async def global_handler(request, exc):
    logger.error("Unhandled exception", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": {"message": "Internal server error"}}
    )
```

## Logging (context over noise)

### What to Log
- **Operation**: What was being attempted
- **Context**: Request ID, user ID (if available), backend name
- **Error details**: Type, message, stack trace
- **Minimal request data**: Model, endpoint (not full payload)

### What NOT to Log
- API keys, tokens, passwords
- Full request/response bodies with sensitive data
- PII (personally identifiable information)
- Secrets from environment variables

### Log Levels
- **ERROR**: Failures requiring attention
- **WARNING**: Recoverable issues (fallback, retry)
- **INFO**: Key events (backend switch, rate limit hit)
- **DEBUG**: Detailed diagnostics (not in production)

### Structured Logging
```python
logger.error(
    "Backend request failed",
    exc_info=True,
    extra={
        "backend_name": "openai",
        "request_id": request_id,
        "model": "gpt-4"
    }
)
```

## Retry Strategy

### When to Retry
- Network timeouts (transient)
- 5xx errors from backends (transient)
- Rate limit errors with Retry-After
- **Only for idempotent operations**

### When NOT to Retry
- 4xx client errors (won't succeed on retry)
- Business logic errors
- Non-idempotent operations without idempotency keys

### Implementation
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(APIConnectionError)
)
async def call_backend(self, request):
    ...
```

## Circuit Breaker

### Health-Aware Backends
Backends implement `IHealthAware`:
```python
class MyBackend(LLMBackend):
    async def on_endpoint_unhealthy(self, api_url, reason):
        # Mark backend as degraded
        self._endpoint_healthy = False
    
    def is_backend_functional(self):
        return self._endpoint_healthy
```

### Routing with Circuit Breaker
```python
async def route_request(self, request):
    for backend in self.backends:
        if backend.is_backend_functional():
            try:
                return await backend.chat_completions(request)
            except BackendError:
                continue  # Try next backend
    raise ServiceUnavailableError("All backends unavailable")
```

## Monitoring & Health

### Health Endpoints
- `/health` - Liveness (is service running?)
- `/health/ready` - Readiness (can accept traffic?)

### Metrics to Track
- Error rate by type
- Backend availability
- Failover frequency
- Rate limit hits
- Response latency

### Alerting
- Spike in 5xx errors
- All backends unhealthy
- SLO breaches (e.g., p95 latency > threshold)

---
_Focus on patterns and decisions. No implementation details or exhaustive lists._
