# OpenAI Chat Completions Frontend

The OpenAI Chat Completions frontend provides full compatibility with the OpenAI Chat Completions API specification. This is the most commonly used frontend, compatible with most OpenAI SDKs, coding agents (Cursor, Windsurf, Cline), and LLM-aware applications.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/chat/completions` | Create a chat completion |
| GET | `/v1/models` | List available models |

## Supported Request Parameters

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `model` | string | Model identifier |
| `messages` | array | Array of message objects |

### Optional Parameters

#### Generation Control

| Parameter | Type | Description |
|-----------|------|-------------|
| `max_tokens` | integer | Maximum tokens to generate |
| `max_completion_tokens` | integer | Maximum completion tokens (newer parameter) |
| `temperature` | number | Sampling temperature (0.0-2.0) |
| `top_p` | number | Nucleus sampling parameter (0.0-1.0) |
| `n` | integer | Number of completions to generate |
| `stop` | string/array | Stop sequences |
| `presence_penalty` | number | Presence penalty (-2.0 to 2.0) |
| `frequency_penalty` | number | Frequency penalty (-2.0 to 2.0) |
| `logit_bias` | object | Token bias adjustments |
| `logprobs` | boolean | Return log probabilities |
| `top_logprobs` | integer | Number of top logprobs to return |
| `seed` | integer | Random seed for reproducibility |

#### Tool Calling

| Parameter | Type | Description |
|-----------|------|-------------|
| `tools` | array | Array of tool/function definitions |
| `tool_choice` | string/object | Tool selection: `none`, `auto`, `required`, or specific tool |
| `parallel_tool_calls` | boolean | Allow parallel tool execution |

#### Response Format

| Parameter | Type | Description |
|-----------|------|-------------|
| `response_format` | object | Response format specification |
| `response_format.type` | string | `text`, `json_object`, or `json_schema` |

#### Streaming

| Parameter | Type | Description |
|-----------|------|-------------|
| `stream` | boolean | Enable streaming responses |
| `stream_options` | object | Streaming configuration |

#### Advanced

| Parameter | Type | Description |
|-----------|------|-------------|
| `user` | string | User identifier |
| `service_tier` | string | Service tier preference |
| `reasoning_effort` | string | Reasoning effort for o-series models |
| `verbosity` | string | Output verbosity for GPT-5 family models (`low`, `medium`, `high`); also settable via URI `?verbosity=...` or backend `extra.verbosity` |
| `modalities` | array | Output modalities (text, audio) |
| `audio` | object | Audio output configuration |
| `prediction` | object | Predicted output for speculative decoding |

#### Proxy-Specific

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | string | Session identifier for proxy tracking |
| `agent` | string | Agent identifier |
| `extra_body` | object | Additional parameters passed to backend |

`extra_body` also supports proxy-only routing hints. For composite selectors that
use `[max_context=N]`, you can set `extra_body.request_context_tokens` to provide
an exact token count for the current request instead of relying on heuristic
token estimation.

Example:

```json
{
  "model": "[max_context=8192]openai:gpt-4o|anthropic:claude-3-5-sonnet",
  "messages": [
    {"role": "user", "content": "Hello"}
  ],
  "extra_body": {
    "request_context_tokens": 9000
  }
}
```

With this override, the proxy skips branches whose `max_context` is smaller than
`9000` for this request.

## Message Format

```json
{
  "role": "user|assistant|system|tool",
  "content": "string or array of content parts",
  "name": "optional name",
  "tool_calls": [...],
  "tool_call_id": "for tool responses"
}
```

### Multimodal Content

```json
{
  "role": "user",
  "content": [
    {"type": "text", "text": "What's in this image?"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
  ]
}
```

## Response Format

### Non-Streaming Response

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "gpt-4o",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Response text..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 20,
    "total_tokens": 30
  }
}
```

### Streaming Response

Server-Sent Events (SSE) format:

```
data: {"id":"chatcmpl-...","choices":[{"delta":{"content":"Hello"}}]}

data: {"id":"chatcmpl-...","choices":[{"delta":{"content":" world"}}]}

data: [DONE]
```

## Example Usage

### Basic Request

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ]
  }'
```

### With Tool Calling

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "user", "content": "What is the weather in San Francisco?"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "Get current weather",
          "parameters": {
            "type": "object",
            "properties": {
              "location": {"type": "string"}
            },
            "required": ["location"]
          }
        }
      }
    ]
  }'
```

### Streaming Request

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "user", "content": "Write a short story"}
    ],
    "stream": true
  }'
```

### JSON Mode

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o",
    "messages": [
      {"role": "user", "content": "List 3 colors as JSON"}
    ],
    "response_format": {"type": "json_object"}
  }'
```

## Backend Routing

Requests to this frontend can be routed to any configured backend:

- **OpenAI**: Native passthrough
- **Anthropic**: Automatic translation to Messages API
- **Gemini**: Automatic translation to generateContent
- **OpenRouter**: OpenAI-compatible passthrough
- **Other backends**: Appropriate translation applied

Use in-chat commands to switch backends dynamically:

```
!/backend(anthropic)
!/model(claude-3-5-sonnet-20241022)
```

## Related Documentation

- [OpenAI Backend](../backends/openai.md) - Configure OpenAI as a backend
- [Frontend Overview](overview.md) - All available frontends
- [Model Name Rewrites](../features/model-name-rewrites.md) - Transform model names
- [URI Model Parameters](../features/uri-model-parameters.md) - Specify parameters in model strings

