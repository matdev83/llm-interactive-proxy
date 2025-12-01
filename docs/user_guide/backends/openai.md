# OpenAI Backend

The OpenAI backend provides access to OpenAI's models through their standard API. This is one of the most commonly used backends and supports all standard OpenAI models including GPT-4, GPT-4o, and GPT-3.5-turbo.

## Overview

The OpenAI backend connects to OpenAI's official API using an API key. It supports both streaming and non-streaming responses, tool calling, and all standard OpenAI features.

## Key Features

- Full support for all OpenAI models (GPT-4, GPT-4o, GPT-3.5-turbo, etc.)
- Streaming and non-streaming responses
- Tool calling (function calling)
- Vision capabilities (with GPT-4 Vision models)
- JSON mode and structured outputs
- Reasoning models (o1-preview, o1-mini)

## Configuration

### Environment Variables

```bash
export OPENAI_API_KEY="sk-..."
```

### CLI Arguments

```bash
# Start proxy with OpenAI as default backend
python -m src.core.cli --default-backend openai

# With specific model
python -m src.core.cli --default-backend openai --force-model gpt-4o
```

### YAML Configuration

```yaml
# config.yaml
backends:
  openai:
    type: openai

default_backend: openai
```

## Usage Examples

### Basic Chat Completion

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

### Streaming Response

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

### Using Reasoning Models

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "o1-preview",
    "messages": [
      {"role": "user", "content": "Solve this complex problem..."}
    ]
  }'
```

## Use Cases

### Production Applications

The OpenAI backend is ideal for production applications that require:

- Reliable, high-quality responses
- Strong reasoning capabilities
- Tool calling for complex workflows
- Vision capabilities for image analysis

### Development and Testing

Use OpenAI models for:

- Prototyping new features
- Testing prompt engineering
- Benchmarking against other providers
- Validating agent behavior

### Cost Optimization

Combine with proxy features for cost control:

- Use `--force-model` to route expensive models to cheaper alternatives
- Enable failover to switch to GPT-3.5-turbo when GPT-4 is unavailable
- Use model name rewrites to dynamically route requests

## OpenAI Responses Backend

The `openai-responses` backend is a specialized connector that targets the `/v1/responses` endpoint (if available) or optimizes for structured output generation. It is primarily used for testing and specific structured data extraction workflows.

### Configuration

```bash
python -m src.core.cli --default-backend openai-responses
```

### YAML Configuration

```yaml
backends:
  openai-responses:
    type: openai-responses
```

## OpenAI Codex Backend

The proxy also supports an `openai-codex` backend that uses ChatGPT login tokens instead of API keys. This allows you to use your ChatGPT Plus/Pro subscription with any OpenAI-compatible client.

### Configuration

```bash
# The backend reads from ~/.codex/auth.json
python -m src.core.cli --default-backend openai-codex
```

For detailed configuration options, see the [OpenAI Codex documentation](../../docs_old/openai_codex.md).

## Model Parameters

You can specify model parameters using URI syntax:

```bash
# With temperature
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai:gpt-4o?temperature=0.7",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

See [URI Model Parameters](../features/uri-model-parameters.md) for more details.

## Troubleshooting

### 401 Unauthorized

- Verify your `OPENAI_API_KEY` is set correctly
- Check that the API key is valid and has not expired
- Ensure you're using the correct authentication header

### 429 Rate Limit Exceeded

- OpenAI has rate limits based on your account tier
- Consider enabling API key rotation with multiple keys
- Use failover to switch to alternative models

### Model Not Found

- Verify the model name is correct (e.g., `gpt-4o`, not `gpt4o`)
- Check that your API key has access to the requested model
- Some models require special access or higher account tiers

### High Latency

- Consider using streaming for better perceived performance
- Use faster models like `gpt-3.5-turbo` for simple tasks
- Enable wire capture to diagnose network issues

## Related Features

- [Model Name Rewrites](../features/model-name-rewrites.md) - Route OpenAI models to other providers
- [Hybrid Backend](../features/hybrid-backend.md) - Combine OpenAI with other models
- [Planning Phase Overrides](../features/planning-phase.md) - Use GPT-4 for planning, GPT-3.5 for execution
- [Edit Precision Tuning](../features/edit-precision.md) - Automatic parameter adjustment for file edits

## Related Documentation

- [Backend Overview](overview.md)
- [Anthropic Backend](anthropic.md)
- [Gemini Backends](gemini.md)
