# Migration Guide: Transitioning to the New API Architecture

This document outlines the process for migrating from the legacy API endpoints to the new versioned API architecture. The new architecture provides better stability, enhanced features, and improved performance.

## Timeline

- **July 2024**: Legacy endpoints are marked as deprecated in code and documentation
- **September 2024**: Legacy endpoints will begin returning deprecation warnings in headers and responses
- **October 2024**: Legacy endpoints will log warnings for each use
- **November 2024**: Legacy code will be completely removed from the codebase
- **December 2024**: Only the new architecture endpoints will be available

### Legacy Code Deprecation Timeline

| Component | Deprecation Date | Removal Date |
|-----------|-----------------|--------------|
| `src/proxy_logic.py` | July 2024 | November 2024 |
| `src/main.py` endpoints | July 2024 | November 2024 |
| Legacy adapters (`src/core/adapters/`) | July 2024 | October 2024 |
| Feature flags | July 2024 | September 2024 |

## API Endpoint Changes

| Legacy Endpoint | New Endpoint | Notes |
|----------------|-------------|-------|
| `/chat/completions` | `/v2/chat/completions` | Full compatibility with improved performance |
| `/v1/chat/completions` | `/v2/chat/completions` | Full compatibility with improved performance |
| `/v1/messages` | `/v2/messages` | Full compatibility with Anthropic-style API |

## Key Differences

The new API architecture maintains backward compatibility with existing requests, but offers several improvements:

1. **Versioned Endpoints**: All new endpoints are explicitly versioned with `/v2/` prefix
2. **Improved Error Handling**: More consistent error formats and better error messages
3. **Enhanced Session Management**: Better session persistence and state management
4. **Optimized Performance**: Reduced latency and improved throughput

## Migration Steps

### 1. Update API Base URL

Change your API client to use the new base URL:

```diff
- const apiUrl = "https://api.example.com/chat/completions";
+ const apiUrl = "https://api.example.com/v2/chat/completions";
```

### 2. Handle Deprecation Headers

If you're using the legacy endpoints during the transition period, be aware of the deprecation headers:

```
Deprecation: true
Sunset: 2023-12-31
```

You can check for these headers to detect when you're using a deprecated endpoint:

```python
response = requests.post("https://api.example.com/chat/completions", json=payload)
if "Deprecation" in response.headers:
    print(f"Warning: Using deprecated API, sunset date: {response.headers['Sunset']}")
```

### 3. Handle Enhanced Response Format

The new API includes additional metadata in responses that you may want to utilize:

```json
{
  "id": "chat-123456",
  "object": "chat.completion",
  "created": 1677858242,
  "model": "gpt-3.5-turbo-0613",
  "usage": {
    "prompt_tokens": 13,
    "completion_tokens": 7,
    "total_tokens": 20
  },
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you today?"
      },
      "finish_reason": "stop",
      "index": 0
    }
  ],
  "metadata": {
    "latency_ms": 250,
    "usage_tier": "standard"
  }
}
```

### 4. Test Your Integration

Before fully switching to the new API, we recommend testing your integration with both endpoints to ensure compatibility:

```bash
# Test legacy endpoint
curl -X POST "https://api.example.com/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# Test new endpoint
curl -X POST "https://api.example.com/v2/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-3.5-turbo",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

## Feature Comparison

| Feature | Legacy API | New API |
|---------|-----------|---------|
| Chat Completions | ✅ | ✅ |
| Streaming Responses | ✅ | ✅ |
| Tool Calling | ✅ | ✅ |
| Loop Detection | ✅ | ✅ (Enhanced) |
| Session Management | ✅ | ✅ (Enhanced) |
| Response Filtering | ✅ | ✅ (Enhanced) |
| Rate Limiting | ✅ | ✅ (Enhanced) |

## Frequently Asked Questions

### Will my existing code break?

No, existing code using the legacy endpoints will continue to work during the transition period. However, we strongly recommend updating to the new endpoints as soon as possible.

### Are there any pricing changes?

No, pricing remains the same regardless of which endpoint you use.

### How can I get help with migration?

Please reach out to our support team at support@example.com or open an issue on our GitHub repository if you encounter any issues during migration.

### Can I use both APIs simultaneously?

Yes, during the transition period you can use both APIs. This allows for a gradual migration of your services.

## Additional Resources

- [API Reference Documentation](/docs/API_REFERENCE.md)
- [Code Examples](/examples/)
- [GitHub Repository](https://github.com/example/api)

