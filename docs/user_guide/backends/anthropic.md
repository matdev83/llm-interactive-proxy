# Anthropic Backend

The Anthropic backend provides access to Claude models through Anthropic's Messages API. Claude models are known for their strong reasoning capabilities, long context windows, and excellent instruction following.

## Overview

The Anthropic backend connects to Anthropic's official API using an API key. It supports both streaming and non-streaming responses, tool calling, and all standard Claude features.

## Key Features

- Full support for all Claude models (Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Haiku)
- Extended context windows (up to 200K tokens)
- Streaming and non-streaming responses
- Tool calling (function calling)
- Vision capabilities
- Strong reasoning and instruction following

## Supported API Features

The Anthropic backend connector provides comprehensive support for the official Anthropic Messages API. The following sections detail all supported request parameters, content types, and response formats.

### Request Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `model` | string | Model identifier (e.g., `claude-3-5-sonnet-20241022`) |
| `messages` | array | Conversation messages with `role` and `content` |
| `max_tokens` | integer | Maximum tokens to generate (required) |
| `system` | string/array | System prompt (string or structured blocks with cache control) |
| `temperature` | float | Sampling temperature (0.0-1.0) |
| `top_p` | float | Nucleus sampling parameter |
| `top_k` | integer | Top-k sampling parameter |
| `stop_sequences` | array | Custom stop sequences |
| `stream` | boolean | Enable streaming responses |
| `metadata` | object | Request metadata including `user_id` |
| `tools` | array | Tool definitions for function calling |
| `tool_choice` | string/object | Tool selection strategy |
| `service_tier` | string | Priority tier (`auto`, `standard_only`) |
| `thinking` | object | Extended thinking configuration |

### Extended Thinking

Enable Claude's extended thinking capability to include the model's reasoning process in responses:

```json
{
  "model": "claude-sonnet-4-20250514",
  "max_tokens": 16000,
  "thinking": {
    "type": "enabled",
    "budget_tokens": 10000
  },
  "messages": [
    {"role": "user", "content": "Solve this complex problem..."}
  ]
}
```

When enabled, responses may include `thinking` content blocks containing the model's step-by-step reasoning. The `budget_tokens` parameter controls how many tokens can be used for thinking.

### Service Tier

Control request prioritization for high-demand periods:

- `"auto"` - Automatic tier selection (default)
- `"standard_only"` - Force standard capacity tier (may queue during high demand)

```json
{
  "model": "claude-3-5-sonnet-20241022",
  "max_tokens": 1024,
  "service_tier": "auto",
  "messages": [...]
}
```

### Multimodal Content

The backend supports multimodal inputs including images and documents.

**Image Content (Base64)**:
```json
{
  "type": "image",
  "source": {
    "type": "base64",
    "media_type": "image/png",
    "data": "<base64-encoded-image>"
  }
}
```

**Image Content (URL)**:
```json
{
  "type": "image",
  "source": {
    "type": "url",
    "url": "https://example.com/image.jpg"
  }
}
```

**Document Content (PDF)**:
```json
{
  "type": "document",
  "source": {
    "type": "base64",
    "media_type": "application/pdf",
    "data": "<base64-encoded-pdf>"
  },
  "title": "document.pdf"
}
```

### System Prompts with Cache Control

System prompts can include cache control hints for prompt caching optimization:

```json
{
  "system": [
    {
      "type": "text",
      "text": "You are a helpful assistant with extensive domain knowledge...",
      "cache_control": {"type": "ephemeral"}
    }
  ],
  "messages": [...]
}
```

### Tool Use / Function Calling

Full support for Anthropic's tool use protocol:

**Tool Definition**:
```json
{
  "tools": [
    {
      "name": "get_weather",
      "description": "Get current weather for a location",
      "input_schema": {
        "type": "object",
        "properties": {
          "location": {"type": "string", "description": "City name"}
        },
        "required": ["location"]
      }
    }
  ]
}
```

**Tool Choice Options**:

| Value | Description |
|-------|-------------|
| `"auto"` | Model decides whether to use tools |
| `"none"` | Disable tool use for this request |
| `{"type": "any"}` | Force the model to use a tool |
| `{"type": "tool", "name": "tool_name"}` | Force use of a specific tool |
| `{"type": "any", "disable_parallel_tool_use": true}` | Force tool use but disable parallel calls |

### Streaming Response Events

When `stream: true`, the backend emits standard Anthropic SSE events:

| Event | Description |
|-------|-------------|
| `message_start` | Initial message metadata (id, model, usage) |
| `content_block_start` | Start of a content block (text, tool_use, thinking) |
| `content_block_delta` | Incremental content updates |
| `content_block_stop` | End of a content block |
| `message_delta` | Message-level updates (stop_reason, usage) |
| `message_stop` | End of message stream |
| `ping` | Keep-alive event |

### Response Fields

| Field | Description |
|-------|-------------|
| `id` | Unique message identifier (e.g., `msg_01XFDUDYJgAACzvnptvVoYEL`) |
| `type` | Always `"message"` |
| `role` | Always `"assistant"` |
| `content` | Array of content blocks (text, tool_use, thinking) |
| `model` | Model used for generation |
| `stop_reason` | Why generation stopped: `end_turn`, `max_tokens`, `stop_sequence`, `tool_use` |
| `stop_sequence` | The matched stop sequence (if `stop_reason` is `stop_sequence`) |
| `usage` | Token usage: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens` |

### Cross-API Translation

When using the Anthropic backend with requests from other API formats (OpenAI, Gemini), the proxy automatically translates parameters:

| Anthropic Feature | OpenAI Equivalent | Gemini Equivalent |
|-------------------|-------------------|-------------------|
| `thinking` | `extra_body.thinking` | `thinkingConfig` |
| `service_tier` | `extra_body.service_tier` | N/A |
| Image blocks | `image_url` content parts | `inlineData` parts |
| Document blocks | Passthrough | Passthrough |
| `tool_choice: any` | `tool_choice: required` | `toolConfig.mode: ANY` |
| `stop_sequences` | `stop` | `stopSequences` |

## Configuration

### Environment Variables

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### CLI Arguments

```bash
# Start proxy with Anthropic as default backend
python -m src.core.cli --default-backend anthropic

# With specific model
python -m src.core.cli --default-backend anthropic --force-model claude-3-5-sonnet-20241022
```

### YAML Configuration

```yaml
# config.yaml
backends:
  anthropic:
    type: anthropic

default_backend: anthropic
```

## Usage Examples

### Basic Chat Completion

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "messages": [
      {"role": "user", "content": "Hello, how are you?"}
    ]
  }'
```

### Using Anthropic Messages API Directly

The proxy also exposes the native Anthropic Messages API:

```bash
curl -X POST http://localhost:8000/anthropic/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: YOUR_PROXY_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [
      {"role": "user", "content": "Hello, Claude!"}
    ]
  }'
```

### Streaming Response

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "messages": [
      {"role": "user", "content": "Write a detailed explanation"}
    ],
    "stream": true
  }'
```

### With Tool Calling

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "messages": [
      {"role": "user", "content": "What is the weather in London?"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "Get the current weather",
          "parameters": {
            "type": "object",
            "properties": {
              "location": {"type": "string"}
            }
          }
        }
      }
    ]
  }'
```

### Long Context Usage

Claude models support very long context windows:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "claude-3-5-sonnet-20241022",
    "messages": [
      {"role": "user", "content": "Analyze this entire codebase: [very long content]"}
    ],
    "max_tokens": 4096
  }'
```

## Use Cases

### Claude Code Integration

The proxy is designed to work seamlessly with Claude Code (Anthropic's CLI tool):

```bash
# Set environment variables
export ANTHROPIC_API_URL=http://localhost:8001
export ANTHROPIC_API_KEY=YOUR_PROXY_KEY

# Launch Claude Code
claude
```

The proxy exposes the Anthropic API on a dedicated port (default: main port + 1) for better compatibility.

### Complex Reasoning Tasks

Claude models excel at:

- Long-form content analysis
- Code review and refactoring
- Complex problem solving
- Detailed explanations
- Following multi-step instructions

### Development and Testing

Use Claude models for:

- Testing different reasoning approaches
- Comparing with other providers
- Validating instruction following
- Long context window testing

## Anthropic OAuth Backend

The proxy also supports an `anthropic-oauth` backend that uses OAuth tokens instead of API keys:

```bash
# Configure OAuth token location
python -m src.core.cli --default-backend anthropic-oauth
```

This is useful for using personal Anthropic accounts without API keys.

## Dedicated Anthropic Port

The proxy can expose the Anthropic API on a dedicated port for better compatibility with Anthropic-specific clients:

### Configuration

```yaml
# config.yaml
proxy:
  anthropic_port: 8001  # Defaults to main port + 1
```

Or via environment variable:

```bash
export ANTHROPIC_PORT=8001
```

### Usage

```bash
# Point Claude Code to the dedicated port
export ANTHROPIC_API_URL=http://localhost:8001
export ANTHROPIC_API_KEY=YOUR_PROXY_KEY
claude
```

## Model Parameters

You can specify model parameters using URI syntax:

```bash
# With temperature
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic:claude-3-5-sonnet-20241022?temperature=0.7",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

See [URI Model Parameters](../features/uri-model-parameters.md) for more details.

## Troubleshooting

### 401 Unauthorized

- Verify your `ANTHROPIC_API_KEY` is set correctly
- Check that the API key is valid and has not expired
- Ensure you're using the correct authentication header (`x-api-key` for native API, `Authorization` for OpenAI-compatible)

### 429 Rate Limit Exceeded

- Anthropic has rate limits based on your account tier
- Consider using API Key Rotation (via multiple backend instances) for load balancing
- Use failover to switch to alternative models

### Model Not Found

- Verify the model name is correct (e.g., `claude-3-5-sonnet-20241022`)
- Check that your API key has access to the requested model
- Some models may require special access

### Context Window Exceeded

- Claude models have large context windows, but they're not unlimited
- Use the proxy's context window enforcement to catch issues early
- Consider summarizing or chunking very long inputs

## Related Features

- [Model Name Rewrites](../features/model-name-rewrites.md) - Route Claude models to other providers
- [Hybrid Backend](../features/hybrid-backend.md) - Combine Claude with other models
- [Angel Verification System](../features/angel-verification.md) - Use Claude for response verification
- [LLM Assessment System](../features/llm-assessment.md) - Use Claude for conversation assessment

## Related Documentation

- [Backend Overview](overview.md)
- [OpenAI Backend](openai.md)
- [Gemini Backends](gemini.md)
