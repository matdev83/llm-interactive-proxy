# Anthropic API Compatibility

This proxy exposes an Anthropic-compatible HTTP surface so that existing code written for the official `anthropic` Python SDK (>= 0.24.0) can be redirected through the proxy with **no code changes other than `base_url`.**

---

## Quick-start

```python
from anthropic import Anthropic

client = Anthropic(
    api_key="ANTHROPIC_API_KEY",              # Your real key – not sent to the proxy
    base_url="http://<proxy-host>:8000/anthropic"  # **Trailing “/anthropic” is required!**
)

resp = client.messages.create(
    model="claude-3-haiku-20240307",
    max_tokens=256,
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.content[0].text)
```

## Path mapping

| SDK call                             | Proxy listens on           | Internally mapped to |
|--------------------------------------|----------------------------|----------------------|
| `POST /anthropic/v1/messages`        | `/anthropic/v1/messages`   | `/v1/chat/completions` |
| `GET  /anthropic/v1/models`          | `/anthropic/v1/models`     | `/v1/models`          |

The conversion layer (`src/anthropic_converters.py`) translates request/response payloads, including streaming ND-JSON ↔ OpenAI-chunk SSE.

## Supported parameters

| Anthropic field      | Notes                                                      |
|----------------------|------------------------------------------------------------|
| `model`              | All Claude-3 family identifiers recognised                |
| `messages[]`         | `user`, `assistant`, optional `system`                    |
| `max_tokens`         | forwarded unchanged                                        |
| `temperature` / `top_p` | forwarded unchanged                                     |
| `stop_sequences`     | mapped to OpenAI `stop` (list)                            |
| `stream`             | SSE stream converted both directions                       |
| `top_k`              | currently ignored (not supported by OpenAI backend)        |

## Authentication

The proxy never forwards your **Anthropic** key upstream – it uses its own configured backend keys. Provide a *dummy* key if your client enforces presence.

## Environment variables

| Variable              | Description                              |
|-----------------------|------------------------------------------|
| `ANTHROPIC_API_KEY`   | Primary key consumed by backend connector|
| `ANTHROPIC_API_KEY_n` | Additional numbered keys for rotation    |

All keys can also be placed in `.env`.

## Limitations

* Tool-use / function-call events are not yet mapped.
* `top_k` is silently dropped.
* Streaming back-pressure is best-effort.

---

_Last updated: 2025-07-14_