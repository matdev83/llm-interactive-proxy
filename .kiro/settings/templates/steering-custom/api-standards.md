# API Standards

[Purpose: consistent API patterns for naming, structure, auth, versioning, and errors]

## Philosophy
- **OpenAI-compatible by default** - Primary API mimics OpenAI for drop-in replacement
- **Predictable, resource-oriented design** - RESTful patterns where applicable
- **Explicit contracts** - Clear request/response schemas
- **Backward compatibility** - Minimize breaking changes

## Endpoint Pattern

### OpenAI Compatibility
```
POST /v1/chat/completions
POST /v1/completions (legacy)
GET  /v1/models
```

### Extension Endpoints
```
GET  /health
GET  /health/ready
GET  /diagnostics
POST /admin/backends/reload
```

**HTTP Verbs**:
- **GET**: Read, safe, idempotent
- **POST**: Create, non-idempotent (unless with idempotency key)
- **PUT**: Full replace (not commonly used)
- **DELETE**: Remove, idempotent

## Request/Response

### Request (OpenAI-compatible)
```json
{
  "model": "gpt-4",
  "messages": [
    {"role": "user", "content": "Hello"}
  ],
  "temperature": 0.7,
  "stream": false
}
```

### Response (Success - Non-streaming)
```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1677652288,
  "model": "gpt-4",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "Hello!"},
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "total_tokens": 15
  }
}
```

### Response (Success - Streaming)
```
data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"},"finish_reason":null}]}

data: [DONE]
```

### Error Response
```json
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

(See `error-handling.md` for complete error standards)

## Status Codes (pattern)

| Code | Meaning | Use Case |
|------|---------|----------|
| 200 | OK | Successful request |
| 400 | Bad Request | Invalid input, validation failure |
| 401 | Unauthorized | Missing or invalid API key |
| 403 | Forbidden | Routing policy violation |
| 404 | Not Found | Unknown endpoint or model |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Unexpected server failure |
| 502 | Bad Gateway | Backend API failure |
| 503 | Service Unavailable | All backends unavailable |

## Authentication

### API Key in Header
```
Authorization: Bearer sk-proj-abc123...
```

### Processing
- Extract from `Authorization` header
- Validate format and presence
- Reject unauthenticated requests before business logic
- Never log API keys

### Error Response
```json
{
  "error": {
    "type": "AuthenticationError",
    "message": "Invalid API key"
  }
}
```

## Versioning

### Strategy
- Version in URL path: `/v1/chat/completions`
- Breaking changes require new version
- Non-breaking changes use same version

### Backward Compatibility
- Additive changes are non-breaking (new optional fields)
- Removing fields/endpoints is breaking
- Changing behavior is breaking
- Provide deprecation window (30+ days)

### Migration
- Announce deprecation in logs and docs
- Support old version during transition
- Hard cutoff after grace period

## Content Negotiation

### Request
- `Content-Type: application/json` (required)
- Streaming uses `Accept: text/event-stream`

### Response
- Non-streaming: `application/json`
- Streaming: `text/event-stream; charset=utf-8`

## Pagination (for list endpoints)

```
GET /v1/models?limit=20&offset=0
```

**Response**:
```json
{
  "object": "list",
  "data": [...],
  "has_more": true
}
```

## Rate Limiting

### Response Headers
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1677652400
```

### Error Response (429)
```json
{
  "error": {
    "type": "RateLimitExceededError",
    "message": "Rate limit exceeded. Retry after 60 seconds.",
    "details": {
      "retry_after": 60
    }
  }
}
```

**HTTP Header**:
```
Retry-After: 60
```

## Extension Headers

### Custom Identity Forwarding
```
X-Proxy-Identity-App: my-app
X-Proxy-Identity-User: user@example.com
```

### Request Tracking
```
X-Request-ID: req-abc123
```

### Backend Selection
```
X-Preferred-Backend: openai
```

---
_Focus on patterns and decisions, not endpoint catalogs._
