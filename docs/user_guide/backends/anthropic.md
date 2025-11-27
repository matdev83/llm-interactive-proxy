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
- Consider enabling API key rotation with multiple keys
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
