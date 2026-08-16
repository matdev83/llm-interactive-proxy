# CommandCode Backends

The proxy includes built-in connector support for CommandCode (`api.commandcode.ai`):
1. `commandcode-openai` (`commandcode_openai` / `commandcode`): OpenAI Chat Completions compatible interface.
2. `commandcode-anthropic` (`commandcode_anthropic`): Anthropic Messages compatible interface.

## Overview

CommandCode is a unified model provider gateway exposing both OpenAI Chat Completions (`/provider/v1/chat/completions`) and Anthropic Messages (`/provider/v1/messages`) endpoints with centralized inventory discovery at `/provider/v1/models`.

## Key Features

- **Direct Upstream Model Naming**: Multi-vendor model IDs (e.g. `Qwen/Qwen3.7-Flash`, `claude-3-5-sonnet-20241022`, `deepseek-ai/DeepSeek-V3`) without artificial vendor namespace prefixes.
- **Cross-API Translation**:
  - Anthropic clients connecting to `/anthropic/v1/messages` can transparently use models hosted behind `commandcode-openai`.
  - OpenAI clients connecting to `/v1/chat/completions` can transparently use models hosted behind `commandcode-anthropic`.
- **Full Streaming & Non-Streaming**: First-class SSE streaming chunks and collected canonical responses.
- **Credential Fallback**: Automatically reads `COMMANDCODE_API_KEY` from the environment if `api_key` is not explicitly passed.

## Configuration

### Environment Variables

```bash
export COMMANDCODE_API_KEY="your-commandcode-api-key"
```

### CLI Arguments

```bash
# Start proxy with commandcode-openai as default backend
python -m src.core.cli --default-backend commandcode-openai
```

### YAML Configuration

```yaml
backends:
  commandcode-openai:
    api_key: ${COMMANDCODE_API_KEY}
    models:
      - "Qwen/Qwen3.7-Flash"
      - "deepseek-ai/DeepSeek-V3"
  commandcode-anthropic:
    api_key: ${COMMANDCODE_API_KEY}
    models:
      - "claude-3-5-sonnet-20241022"
      - "claude-haiku-4-5-20251001"

default_backend: commandcode-openai
```

## Usage Examples

### 1. OpenAI Chat Completions (Native OpenAI Endpoint)

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen3.7-Flash",
    "messages": [{"role": "user", "content": "Hello CommandCode"}],
    "stream": false
  }'
```

### 2. Anthropic Messages (Cross-API to OpenAI Backend)

```bash
curl -X POST http://localhost:8000/anthropic/v1/messages \
  -H "Content-Type: application/json" \
  -H "anthropic-version: 2023-06-01" \
  -d '{
    "model": "Qwen/Qwen3.7-Flash",
    "messages": [{"role": "user", "content": "Hello CommandCode"}],
    "max_tokens": 100
  }'
```
