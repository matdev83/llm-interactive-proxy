# Ollama Backend (Local)

The Ollama backend provides connectivity to a locally running Ollama server (`<http://localhost:11434>`) via its OpenAI-compatible API. It enables you to use models you have pulled locally **and** access cloud-hosted models that the Ollama app routes automatically to their proper remote providers.

> **Important:** This connector (`ollama`) is **only for connecting to a local Ollama instance**. A separate remote connector (`ollama-com`) will be added in the future for direct cloud access without a local server.

## Overview

Ollama runs locally on your machine and serves models you've pulled via `ollama pull`. It exposes an OpenAI-compatible REST endpoint, meaning many tools and connectors that work with OpenAI's API work with minimal changes. This connector is that minimal wrapper around the OpenAI connector, configured to talk to `http://localhost:11434/v1` by default.

## Key Features

- **No API key required** — Ollama serves local models without authentication by default
- **OpenAI-compatible** — works with the same request/response format as OpenAI backends
- **Local + Cloud model access** — during startup the connector discovers both locally-pulled models and cloud-capable models from `<https://ollama.com/api/tags>`
- **Automatic model suffixing** — cloud models are listed with a `-cloud` suffix so you can distinguish them from local ones

## Model Discovery

On initialization the connector returns a combined list:

| Source | How Discovered | Naming |
|--------|---------------|--------|
| **Local models** | `GET /v1/models` from local Ollama server | e.g. `llama3:latest`, `codellama:7b` |
| **Cloud models** | `<https://ollama.com/api/tags>` (cached for 30 min) | e.g. `llama3:latest-cloud`, `deepseek-v3.2-cloud` |

To use a cloud-hosted model, include the `-cloud` suffix in the model name:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "llama3:latest-cloud",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

Without the suffix the request is routed to the local Ollama server, which must have the model downloaded (`ollama pull llama3:latest`).

You can browse the full list of cloud-capable models on the [Ollama cloud models page](https://ollama.com/search?c=cloud).

## Configuration

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `OLLAMA_API_BASE_URL` | Override the local Ollama server URL | `http://localhost:11434/v1` |
| `OLLAMA_TIMEOUT` | Request timeout | None (connector default) |
| `OLLAMA_API_KEY` | Optional API key (only needed if Ollama sits behind an authenticated proxy) | None |

### YAML Configuration

```yaml
# config.yaml
backends:
  ollama:
    type: ollama
    api_url: "http://localhost:11434/v1"  # optional, this is the default

default_backend: ollama
```

### Starting the Proxy

```bash
# Start with Ollama as default backend
python -m src.core.cli --default-backend ollama

# Or via config file
python -m src.core.cli --config config/config.yaml
```

## Important Notes

- **Local server required**: The `ollama` connector requires a running Ollama instance on the configured URL. Make sure `ollama serve` is active.
- **Cloud routing**: When you request a model with the `-cloud` suffix, Ollama itself handles routing the request to the proper remote provider. The proxy simply passes the request through.
- **Payload compatibility**: The connector strips OpenAI-specific fields that Ollama's gateway rejects (`stream_options`, `reasoning`, `reasoning_effort`, `max_completion_tokens`).

## Related Documentation

- [Backend Overview](overview.md)
- [OpenAI Backend](openai.md)
- [Ollama Website](https://ollama.com/)
- [Ollama Cloud Models](https://ollama.com/search?c=cloud)
