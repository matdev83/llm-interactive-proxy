# ZenMux Backend

The ZenMux backend provides access to ZenMux's API, offering a unified interface for various AI models.

## Overview

ZenMux is an AI model aggregator that provides access to multiple models through a single API. The proxy supports the `zenmux` backend for easy integration.

## Key Features

- OpenAI-compatible API
- Access to multiple models
- Unified billing and management

## Configuration

### Environment Variables

```bash
export ZENMUX_API_KEY="..."
```

### CLI Arguments

```bash
# Start proxy with ZenMux as default backend
python -m src.core.cli --default-backend zenmux
```

### YAML Configuration

```yaml
# config.yaml
backends:
  zenmux:
    type: zenmux

default_backend: zenmux
```

## Usage Examples

### Basic Chat Completion

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "zenmux/model-name",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

## Related Documentation

- [Backend Overview](overview.md)
- [OpenRouter Backend](openrouter.md)

