# Anthropic Messages API Frontend

The Anthropic Messages API frontend provides full compatibility with the Anthropic Claude API specification. This frontend is used by Claude Code, the Anthropic SDK, and other Claude-compatible clients.

## Endpoints

The proxy exposes Anthropic endpoints in two ways:

### Namespaced Endpoints (Main Port)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/anthropic/v1/messages` | Create a message |
| GET | `/anthropic/v1/models` | List available models |
| GET | `/anthropic/v1/health` | Health check |
| GET | `/anthropic/v1/info` | Service information |

### Dedicated Server (Separate Port)

When running with `--anthropic-compat-port` (default: 8001), the proxy exposes root-level endpoints:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/messages` | Create a message |
| GET | `/v1/models` | List available models |

This is useful for clients that expect Anthropic API at the root path.

## Supported Request Parameters

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `model` | string | Model identifier (e.g., `claude-3-5-sonnet-20241022`) |
| `messages` | array | Array of message objects |

### Optional Parameters

#### Generation Control

| Parameter | Type | Description |
|-----------|------|-------------|
| `max_tokens` | integer | Maximum tokens to generate |
| `temperature` | number | Sampling temperature (0.0-1.0) |
| `top_p` | number | Nucleus sampling parameter |
| `top_k` | integer | Top-k sampling parameter |
| `stop_sequences` | array | Stop sequences |

#### System Message

| Parameter | Type | Description |
|-----------|------|-------------|
| `system` | string/array | System prompt (string or array of text blocks with cache_control) |

#### Tool Use

| Parameter | Type | Description |
|-----------|------|-------------|
| `tools` | array | Array of tool definitions |
| `tool_choice` | string/object | Tool selection strategy |

#### Streaming

| Parameter | Type | Description |
|-----------|------|-------------|
| `stream` | boolean | Enable streaming responses |

#### Advanced

| Parameter | Type | Description |
|-----------|------|-------------|
| `metadata` | object | Request metadata |
| `service_tier` | string | Service tier: `auto`, `standard_only` |
| `thinking` | object | Extended thinking configuration for reasoning |

## Message Format

### User Message

```json
{
  "role": "user",
  "content": "What is the capital of France?"
}
```

### User Message with Multimodal Content

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "What's in this image?"},
    {
      "type": "image",
      "source": {
        "type": "base64",
        "media_type": "image/png",
        "data": "iVBORw0KGgoAAAANSUhEUgAA..."
      }
    }
  ]
}
```

### Assistant Message

```json
{
  "role": "assistant",
  "content": "The capital of France is Paris."
}
```

### Tool Use Message

```json
{
  "role": "assistant",
  "content": [
    {
      "type": "tool_use",
      "id": "toolu_01A09q90qw90lq917835lgs",
      "name": "get_weather",
      "input": {"location": "San Francisco"}
    }
  ]
}
```

### Tool Result Message

```json
{
  "role": "user",
  "content": [
    {
      "type": "tool_result",
      "tool_use_id": "toolu_01A09q90qw90lq917835lgs",
      "content": "Sunny, 72F"
    }
  ]
}
```

## Response Format

### Non-Streaming Response

```json
{
  "id": "msg_01XFDUDYJgAACzvnptvVoYEL",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "The capital of France is Paris."
    }
  ],
  "model": "claude-3-5-sonnet-20241022",
  "stop_reason": "end_turn",
  "stop_sequence": null,
  "usage": {
    "input_tokens": 25,
    "output_tokens": 15
  }
}
```

### Streaming Response

Server-Sent Events (SSE) format:

```
event: message_start
data: {"type":"message_start","message":{"id":"msg_01...","type":"message","role":"assistant","content":[],"model":"claude-3-5-sonnet-20241022"}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"The capital"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" of France"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":15}}

event: message_stop
data: {"type":"message_stop"}
```

## Example Usage

### Basic Request

```bash
curl -X POST http://localhost:8000/anthropic/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_PROXY_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ]
  }'
```

### With System Prompt

```bash
curl -X POST http://localhost:8000/anthropic/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_PROXY_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "system": "You are a helpful assistant that speaks like a pirate.",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

### With Tool Use

```bash
curl -X POST http://localhost:8000/anthropic/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_PROXY_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "What is the weather in San Francisco?"}
    ],
    "tools": [
      {
        "name": "get_weather",
        "description": "Get the current weather for a location",
        "input_schema": {
          "type": "object",
          "properties": {
            "location": {"type": "string", "description": "City name"}
          },
          "required": ["location"]
        }
      }
    ]
  }'
```

### Streaming Request

```bash
curl -X POST http://localhost:8000/anthropic/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_PROXY_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "stream": true,
    "messages": [
      {"role": "user", "content": "Write a short poem"}
    ]
  }'
```

### Using Dedicated Port

```bash
# Connect to dedicated Anthropic port (default 8001)
curl -X POST http://localhost:8001/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_PROXY_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

## Required Headers

| Header | Value | Description |
|--------|-------|-------------|
| `Content-Type` | `application/json` | Required for all requests |
| `x-api-key` | Your API key | Authentication (or use `Authorization: Bearer`) |
| `anthropic-version` | `2023-06-01` | API version (recommended) |

## Backend Routing

Requests to the Anthropic frontend can be routed to any configured backend:

- **Anthropic**: Native passthrough
- **OpenAI**: Automatic translation to Chat Completions
- **Gemini**: Automatic translation to generateContent
- **Other backends**: Appropriate translation applied

## Configuration

### Enable Dedicated Port

```bash
python -m src.core.cli --anthropic-compat-port 8001
```

### YAML Configuration

```yaml
anthropic_compat_port: 8001
```

## Related Documentation

- [Anthropic Backend](../backends/anthropic.md) - Configure Anthropic as a backend
- [Anthropic OAuth Backend](../backends/anthropic-oauth.md) - OAuth authentication
- [Frontend Overview](overview.md) - All available frontends

