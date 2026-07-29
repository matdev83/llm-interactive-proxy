# Alibaba Token Plan (International)

The `alibaba-token-plan-intl` backend connects to Alibaba Cloud Model Studio Token Plan Team Edition in the international `ap-southeast-1` region. It uses Alibaba's Anthropic-compatible Messages API for completions.

## Authentication

Set the plan-specific API key in the proxy process environment:

```bash
export ALIBABA_TOKEN_PLAN_API_KEY="sk-sp-..."
```

On PowerShell:

```powershell
$env:ALIBABA_TOKEN_PLAN_API_KEY = "sk-sp-..."
```

The connector always reads this environment variable at runtime. It does not accept an API key from YAML or another configuration-file field. Token Plan, Coding Plan, and standard Model Studio keys and endpoints are separate; use the Token Plan-specific key and matching endpoint to avoid authentication failures or unintended billing.

## Starting The Proxy

```bash
python -m src.core.cli --default-backend alibaba-token-plan-intl
```

Select a model using the standard explicit backend selector:

```text
alibaba-token-plan-intl:qwen3.7-plus
```

Use the colon form for explicit routing. Model IDs returned by `/v1/models` are discovery identifiers and may use a slash-prefixed display form.

## Model Discovery

The backend does not hardcode Token Plan models. During backend initialization it queries Alibaba's Token Plan `/models` catalog, caches the resulting connector-instance snapshot, and publishes the models through the proxy's standard discovery and routing interfaces. This ensures `/v1/models` and automated routing expose only models currently enabled for the plan rather than the full Alibaba Model Studio catalog.

Alibaba does not expose model enumeration on its Anthropic-compatible endpoint. The connector therefore obtains the catalog from the matching Token Plan OpenAI-compatible `/models` endpoint while continuing to use Anthropic Messages for completions.

A direct `list_models()` call refreshes the remote catalog. Normal proxy discovery and routing use the cached snapshot populated during initialization.

## Endpoint Configuration

Completions default to the official international Token Plan Anthropic endpoint:

```text
https://token-plan.ap-southeast-1.maas.aliyuncs.com/apps/anthropic/v1
```

The completion endpoint can be overridden with `anthropic_api_base_url` or `api_base_url` in backend configuration for a compatible gateway or testing proxy. Authentication remains environment-only. Model discovery continues to use the official matching Token Plan catalog endpoint.

## Message Compatibility

Alibaba's Token Plan Messages endpoint is stricter than the standard Anthropic API for message roles. The connector preserves `system` and `user`; every other incoming role, including `assistant`, `developer`, and unknown roles, is converted to `user` before transmission. System content is emitted through the Anthropic top-level `system` field.

The backend supports streaming through the proxy's OpenAI Chat Completions frontend:

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer $LLM_PROXY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "alibaba-token-plan-intl:qwen3.7-plus",
    "messages": [{"role": "user", "content": "Hello"}],
    "stream": true
  }'
```
