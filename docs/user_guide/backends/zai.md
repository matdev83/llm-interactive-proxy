# ZAI Backend

The ZAI backend provides access to Zhipu AI (Z.ai) models through an OpenAI-compatible API. ZAI offers powerful Chinese language models and coding-specific models.

## Overview

ZAI (Zhipu AI) is a Chinese AI company that provides access to various language models, including GLM models and specialized coding models. The proxy supports two ZAI backend configurations: standard `zai` and `zai-coding-plan` for coding-specific workflows.

## Key Features

- OpenAI-compatible API
- Strong Chinese language support
- Specialized coding models
- Competitive pricing
- Streaming and non-streaming responses

## Configuration

### Environment Variables

```bash
# Standard ZAI backend (Zhipu public API)
export ZAI_API_KEY="..."

# ZAI Coding Plan backend (GLM Coding Plan subscription)
export ZAI_CODING_PLAN_API_KEY="..."
```

### CLI Arguments

```bash
# Start proxy with ZAI as default backend
python -m src.core.cli --default-backend zai

# Or use the coding plan backend
python -m src.core.cli --default-backend zai-coding-plan
```

### YAML Configuration

```yaml
# config.yaml
backends:
  zai:
    type: zai
  zai-coding-plan:
    type: zai-coding-plan

default_backend: zai
```

## Backend Variants

### Standard ZAI Backend

The standard `zai` backend provides access to all ZAI models:

```bash
python -m src.core.cli --default-backend zai
```

### ZAI Coding Plan Backend

The `zai-coding-plan` backend is optimized for coding workflows and works with any supported front-end and coding agent:

```bash
python -m src.core.cli --default-backend zai-coding-plan
```

This backend is specifically designed for:

- Code generation and completion
- Code review and refactoring
- Debugging assistance
- Technical documentation

## Usage Examples

### Basic Chat Completion

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "glm-4",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

### Coding Task

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "glm-4",
    "messages": [
      {"role": "user", "content": "Write a Python function to sort a list"}
    ]
  }'
```

### Streaming Response

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "glm-4",
    "messages": [
      {"role": "user", "content": "Explain async programming"}
    ],
    "stream": true
  }'
```

### Chinese Language Task

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "glm-4",
    "messages": [
      {"role": "user", "content": "请解释一下机器学习的基本概念"}
    ]
  }'
```

## Use Cases

### Chinese Language Applications

ZAI models excel at:

- Chinese language understanding and generation
- Chinese-English translation
- Chinese text analysis
- Chinese content creation

### Coding Workflows

The `zai-coding-plan` backend is ideal for:

- Code generation in multiple languages
- Code review and suggestions
- Debugging assistance
- Technical documentation generation
- Integration with coding agents

### Cost-Effective Alternative

Use ZAI as:

- A cost-effective alternative to Western providers
- A specialized option for Chinese language tasks
- A coding-focused backend for development workflows

## Known Limitations

### Reasoning Payloads

Reasoning payloads are currently stripped due to provider limitations. This means:

- Reasoning models may not work as expected
- Thinking/reasoning output is not preserved
- Use standard models for best results

If you need reasoning capabilities, consider using other backends like OpenAI (o1 models) or the Hybrid Backend.

## Model Parameters

You can specify model parameters using URI syntax:

```bash
# With temperature
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "zai:glm-4?temperature=0.7",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

See [URI Model Parameters](../features/uri-model-parameters.md) for more details.

## Troubleshooting

### 401 Unauthorized

- Verify your `ZAI_API_KEY` is set correctly
- Check that the API key is valid and has credits
- Ensure you're using the correct authentication header

### 429 Rate Limit Exceeded

- ZAI has rate limits based on your account tier
- Consider upgrading your account for higher limits
- Use failover to switch to alternative models

### Model Not Found

- Verify the model name is correct (e.g., `glm-4`)
- Check that your API key has access to the requested model
- Some models may require special access

### Chinese Character Encoding Issues

- Ensure your client is using UTF-8 encoding
- Check that the proxy is configured to handle UTF-8
- Verify that your terminal/client supports Chinese characters

### Reasoning Not Working

- Remember that reasoning payloads are stripped for ZAI
- Use standard models instead of reasoning models
- Consider using other backends for reasoning tasks

## Integration with Coding Agents

The `zai-coding-plan` backend works seamlessly with coding agents:

```bash
# Point your coding agent to the proxy
export OPENAI_API_BASE=http://localhost:8000/v1
export OPENAI_API_KEY=YOUR_PROXY_KEY

# Start the proxy with ZAI coding plan
python -m src.core.cli --default-backend zai-coding-plan

# Your coding agent will now use ZAI models
```

## Related Features

- [Model Name Rewrites](../features/model-name-rewrites.md) - Route models to ZAI
- [Hybrid Backend](../features/hybrid-backend.md) - Combine ZAI with other models
- [Edit Precision Tuning](../features/edit-precision.md) - Optimize for coding tasks

## Related Documentation

- [Backend Overview](overview.md)
- [OpenAI Backend](openai.md)
- [Qwen Backend](qwen.md)
