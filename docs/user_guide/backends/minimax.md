# MiniMax Backend

The MiniMax backend provides access to MiniMax (Hailuo AI) models through their OpenAI-compatible API. MiniMax offers powerful reasoning models and general-purpose language models.

## Overview

MiniMax (Hailuo AI) is a Chinese AI company known for its advanced reasoning models (like `MiniMax-M2`) and strong general-purpose models. The proxy supports the `minimax` backend for accessing these models.

## Key Features

- OpenAI-compatible API
- Strong reasoning capabilities (MiniMax-M2)
- High-quality general-purpose models
- Competitive pricing
- Streaming and non-streaming responses

## Configuration

### Environment Variables

```bash
export MINIMAX_API_KEY="..."
```

### CLI Arguments

```bash
# Start proxy with MiniMax as default backend
python -m src.core.cli --default-backend minimax

# With specific model
python -m src.core.cli --default-backend minimax --force-model MiniMax-M2
```

### YAML Configuration

```yaml
# config.yaml
backends:
  minimax:
    type: minimax

default_backend: minimax
```

## Available Models

- **MiniMax-M2**: Advanced reasoning model, excellent for complex tasks
- **abab6.5s**: General-purpose model
- **abab6.5t**: Turbo model for faster responses

## Usage Examples

### Basic Chat Completion

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "MiniMax-M2",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

### Reasoning Task

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "MiniMax-M2",
    "messages": [
      {"role": "user", "content": "Solve this logic puzzle..."}
    ]
  }'
```

### Streaming Response

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "MiniMax-M2",
    "messages": [
      {"role": "user", "content": "Explain quantum physics"}
    ],
    "stream": true
  }'
```

## Use Cases

### Hybrid Backend Reasoning

MiniMax-M2 is highly recommended as a reasoning model in the Hybrid Backend configuration:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]",
    "messages": [{"role": "user", "content": "Complex coding task"}]
  }'
```

See [Hybrid Backend](../features/hybrid-backend.md) for details.

### Complex Problem Solving

MiniMax models excel at:

- Logical reasoning
- Mathematical problem solving
- Complex instruction following
- Strategic planning

## Related Features

- [Hybrid Backend](../features/hybrid-backend.md) - Combine MiniMax with execution models
- [Model Name Rewrites](../features/model-name-rewrites.md) - Route models to MiniMax

## Related Documentation

- [Backend Overview](overview.md)
- [OpenAI Backend](openai.md)
- [Qwen Backend](qwen.md)
