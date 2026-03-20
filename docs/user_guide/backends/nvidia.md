# Nvidia Backend

The Nvidia backend routes chat completions to NVIDIA’s OpenAI-compatible inference surface (hosted [NVIDIA API](https://docs.api.nvidia.com/nim/reference/llm-apis) integrator or a self-hosted NIM deployment you point at with `api_url`).

## Overview

The proxy registers backend type `nvidia`. It uses the same OpenAI-style chat completion and streaming paths as other API-key OpenAI-compatible connectors, so clients keep using your existing frontends (for example OpenAI Chat Completions).

## Key features

- OpenAI-compatible `POST /v1/chat/completions` and model listing via `GET /v1/models` when credentials allow
- Outbound requests map `max_completion_tokens` to `max_tokens` when needed: the hosted NIM integrator uses a strict request schema and rejects `max_completion_tokens` as an unknown field
- The connector omits `stream_options` (for example `include_usage`) from outbound chat bodies: the same strict schema often rejects that nested object even though other OpenAI-compatible providers accept it
- Default hosted base URL `https://integrate.api.nvidia.com/v1` (overridable for self-hosted NIM)
- API key via environment variable `NVIDIA_API_KEY` when no key is supplied through higher-precedence initialization (see [Configuration](#configuration))

## Configuration

### Environment variables

```bash
export NVIDIA_API_KEY="..."
```

Use a **NVIDIA Build inference API key** (commonly `nvapi-...`). Prefer environment variables for secrets; do not commit real keys in YAML. If you copy the key with a `Bearer ` prefix or stray spaces, the connector strips those before calling the API.

### Credential precedence

- Proxy-wide configuration precedence is **CLI > ENV > YAML** where those layers apply.
- For this connector specifically: if an `api_key` is passed into connector initialization (for example from YAML), it **overrides** `NVIDIA_API_KEY`. The environment variable is used only when initialization does not already supply an API key (same pattern as ZenMux).

If you see **401 Unauthorized** from NVIDIA while the same key works in a direct client, check that YAML `backends.nvidia.api_key` is not set to a different value (for example your proxy’s own client key). Remove the field or leave it empty so `NVIDIA_API_KEY` is picked up.

### CLI arguments

```bash
# Example: default backend and model
python -m src.core.cli --default-backend nvidia --force-model meta/llama3-70b
```

### YAML configuration

Uncomment and adjust the example under `backends:` in `config/config.example.yaml`. Typical fields:

- `api_url` — optional; omit for hosted default, or set to your self-hosted NIM OpenAI base URL.
- `timeout` — optional request timeout.
- `models` — optional static list; if there is **no** usable API key and **no** static list, model discovery yields an **empty** catalog (the backend does not appear as a selectable target where listings depend on discovered models).

```yaml
backends:
  nvidia:
    timeout: 120
    # api_url: "https://your-nim-host/v1"
```

## Model selection and `backend:model`

Use the `nvidia:` prefix with the **upstream** model id as documented by NVIDIA (often vendor-qualified), for example:

- `nvidia:meta/llama3-70b`

Model ids and availability depend on your NVIDIA account and deployment. See the vendor [LLM APIs](https://docs.api.nvidia.com/nim/reference/llm-apis) and [models](https://docs.api.nvidia.com/nim/reference/models-1) references for current names and constraints.

### Example request

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "nvidia:meta/llama3-70b",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

## Connector proof: model enumeration + completion

The Nvidia backend inherits `OpenAIConnector.list_models()` (`GET {api_base}/models`) and `get_available_models()` (cached ids after `initialize`), same pattern as other OpenAI-compatible connectors.

- **Mocked upstream (no API key):** exercises `NvidiaConnector` in-process with `respx` stubs:

  ```bash
  ./.venv/Scripts/python.exe dev/scripts/prove_nvidia_connector_respx.py
  ```

  Regression: `pytest tests/integration/test_nvidia_connector_in_process_respx.py`.

- **Live NVIDIA API:** calls the real integrator with your key (set `NV_PROVE_MODEL` to force a catalog id):

  ```bash
  export NVIDIA_API_KEY="..."
  ./.venv/Scripts/python.exe dev/scripts/prove_nvidia_connector_live.py
  ```

  The script disables the connector’s first-use health check (extra `GET /models`) so progress does not pause silently before chat, prints the chat URL and httpx timeouts, and honors `NV_PROVE_READ_TIMEOUT` / `NV_PROVE_CONNECT_TIMEOUT` if inference is slow.

## End-to-end validation (Step-3.5-Flash)

To prove the Nvidia connector against the hosted API (list models, then a short non-streaming chat via the proxy), use the development script (requires a valid `NVIDIA_API_KEY` with access to the upstream model, default `stepfun-ai/step-3.5-flash` per [NVIDIA Build](https://build.nvidia.com/stepfun-ai/step-3.5-flash)):

```bash
export NVIDIA_API_KEY="..."
./.venv/Scripts/python.exe dev/scripts/validate_nvidia_glm_e2e.py
```

Optional: `NV_E2E_PORT`, `NV_E2E_UPSTREAM_MODEL`, or `NV_E2E_BASE_URL` (reuse an already-running proxy). See the script docstring in `dev/scripts/validate_nvidia_glm_e2e.py`.

For CI or offline proof of the HTTP path (mocked NVIDIA upstream, Step-3.5-Flash-shaped responses), run:

```bash
./.venv/Scripts/python.exe -m pytest tests/integration/test_nvidia_backend_http_e2e.py -q
```

## Usage accounting

- **Non-streaming**: When the upstream JSON response includes an OpenAI-style `usage` object, the proxy preserves it for accounting like other OpenAI-compatible backends.
- **Streaming**: Usage is recorded when the stream includes an OpenAI-style final SSE chunk with a `usage` field, consistent with the shared translation path. If a given upstream deployment omits stream usage, aggregate usage for that stream may be incomplete.

## Related documentation

- [Backend overview](overview.md)
- [OpenRouter backend](openrouter.md) (another OpenAI-compatible multi-model path)
