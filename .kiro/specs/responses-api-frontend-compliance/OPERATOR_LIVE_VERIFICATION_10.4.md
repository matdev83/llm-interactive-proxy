# Task 10.4 — Live-through-proxy verification (operator playbook)

Use this when an environment has **real provider credentials** and a running proxy. Do not treat mocked `TestClient` / patched `RequestProcessor` integration tests as completion of task 10.4.

## Conversation linkage and horizontal scaling (Requirement 3.3)

The client-facing `/v1/responses` frontend resolves `previous_response_id` using the in-process [`InMemoryResponsesSessionStore`](../../../src/core/services/in_memory_responses_session_store.py) (TTL-backed). That matches the spec’s **phase 1** design: follow-up linkage is **reliable within a single proxy process**.

If you run **multiple workers or processes** behind a load balancer without sticky routing, a valid `previous_response_id` may hit a different worker than the one that stored the prior response and the client will see `previous_response_id` / “not found” style errors even though the id was valid on another instance. Supported operating models until a shared store exists:

- **Single worker / single process** (simplest), or  
- **Sticky sessions** so follow-up requests for the same conversation land on the same worker, or  
- A future **shared** `IResponsesSessionStore` implementation (out of scope for the current in-memory default).

Document your deployment choice so operators do not assume cross-worker linkage with the default store.

## Prerequisites

1. **Python**: project venv — `./.venv/Scripts/python.exe` (Windows) or `./.venv/bin/python` (Unix).
2. **Config**: `config/config.yaml` from `config/config.example.yaml`; set `auth.disable_auth: true` for local runs *or* configure proxy API keys and send `Authorization: Bearer <key>` on every call.
3. **Credentials** (export before start, values not committed):
   - Native OpenAI Responses path: `OPENAI_API_KEY`
   - Translated path (pick one): `ANTHROPIC_API_KEY` and/or `GEMINI_API_KEY` (or `GOOGLE_API_KEY` per your Gemini setup)
4. **Backends in YAML**: ensure `openai` or `openai-responses`, plus `anthropic` and/or `gemini`, are enabled with keys resolved from env (see `docs/user_guide/backends/overview.md`).

## Minimal config snippet

Start from `config/config.example.yaml` and make sure the active config contains at least the following shape:

```yaml
host: "127.0.0.1"
port: 8000

auth:
  disable_auth: true

backends:
  default_backend: openai-responses
  openai:
    type: openai
  openai-responses:
    type: openai-responses
  anthropic:
    type: anthropic
  gemini:
    type: gemini

responses_api:
  websocket:
    frontend_enabled: true
    backend_enabled: true
    frontend_path: "/v1/responses"
    connection_timeout: 3600
    max_connections: 100
```

Notes:

- `responses_api.websocket.*` defaults live in `config/config.example.yaml` and are disabled by default there.
- Keep model selectors explicit during verification, even if `default_backend` is set.
- If you want to verify HTTP only, `frontend_enabled` / `backend_enabled` can stay `false`, but leave them `true` if you also plan to run the WebSocket checks in the same session.

## Start the proxy

From repo root:

```powershell
Set-Location C:\Users\Mateusz\source\repos\llm-interactive-proxy
$env:OPENAI_API_KEY = "<secret>"
$env:ANTHROPIC_API_KEY = "<secret>"   # if exercising Anthropic translated path
$env:GEMINI_API_KEY = "<secret>"      # if exercising Gemini translated path
./.venv/Scripts/python.exe -m src.core.cli --config config/config.yaml
```

Use `--default-backend` if you rely on unprefixed models (e.g. `--default-backend openai-responses`). Prefer **explicit** `backend:model` selectors below so routing is unambiguous.

Base URL in examples: `http://127.0.0.1:8000` and `ws://127.0.0.1:8000` (match `host` / `port` in config).

## Quick preflight checks

In a second terminal, confirm the process is reachable before running the verification matrix:

```powershell
curl.exe -i http://127.0.0.1:8000/health
curl.exe -i http://127.0.0.1:8000/v1/models
```

Expected:

- `/health` returns `200`
- `/v1/models` returns `200` and includes at least the backend families you intend to test

## Recommended execution matrix

Run these in order so evidence is easy to interpret:

1. Native Responses path, HTTP non-streaming
2. Native Responses path, HTTP streaming SSE
3. Translated path, HTTP non-streaming
4. Translated path, HTTP streaming SSE
5. Optional WebSocket path on one native backend and one translated backend if enabled
6. Optional follow-up request using `previous_response_id` against at least one backend flavor

## A) Native Responses backend path (HTTP)

**Selector (example):** `openai-responses:gpt-4o-mini`  
(Alternative: `openai:gpt-4o-mini` — controller still uses `OpenAIResponsesProjector` for `openai` / `openai-responses` backends; `openai-responses` targets provider `/v1/responses` per backend docs.)

### A1. Non-streaming smoke check

```powershell
curl.exe -sS -X POST "http://127.0.0.1:8000/v1/responses" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"openai-responses:gpt-4o-mini\",\"input\":\"Say hello in one short sentence.\"}"
```

**Assertions**

- HTTP `200`
- JSON body has top-level `object: "response"`
- JSON body has non-empty `id`
- JSON body has `output` and/or equivalent completed response content expected by the frontend contract

### A2. Streaming SSE check

```bash
curl.exe -sN -X POST "http://127.0.0.1:8000/v1/responses" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"openai-responses:gpt-4o-mini\",\"input\":\"Say hello in one short sentence.\",\"stream\":true}"
```

On Unix shells, use a single line or single-quoted JSON.

**Assertions**

- HTTP `200`, `Content-Type` contains `text/event-stream`.
- Parsed SSE `data:` lines (JSON) include official Responses event types in order: e.g. `response.created`, progress/output events, then terminal `response.completed` (or `response.failed` / `response.incomplete` on error paths).
- Final SSE sentinel line `data: [DONE]` after the terminal event (proxy contract; see pinned fixtures under `tests/integration/fixtures/responses_api_frontend/`).
- Response `id` and `output` items are non-empty on success; optional: capture `response.id` for a follow-up `previous_response_id` test.

### A3. Follow-up continuity check

Reuse the `response.id` from A1 or the terminal event from A2:

```powershell
curl.exe -sS -X POST "http://127.0.0.1:8000/v1/responses" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"openai-responses:gpt-4o-mini\",\"input\":\"Continue in one more sentence.\",\"previous_response_id\":\"<response-id-from-A1-or-A2>\"}"
```

**Assertions**

- HTTP `200`
- No `previous_response_not_found` error
- Result is semantically a continuation rather than a fresh unrelated answer

## B) Translated backend-flavor path (HTTP)

**Selector (Anthropic example):** `anthropic:claude-3-5-haiku-20241022`  
**Selector (Gemini example):** `gemini:gemini-2.0-flash` (adjust to a model id present in your catalog)

### B1. Anthropic translated path

```bash
curl.exe -sN -X POST "http://127.0.0.1:8000/v1/responses" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"anthropic:claude-3-5-haiku-20241022\",\"input\":\"Say hello in one short sentence.\",\"stream\":true}"
```

### B2. Gemini translated path

```bash
curl.exe -sN -X POST "http://127.0.0.1:8000/v1/responses" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"gemini:gemini-2.0-flash\",\"input\":\"Say hello in one short sentence.\",\"stream\":true}"
```

### B3. Explicit limitation check on a translated path

Use a feature that current tests pin as unsupported for Anthropic or Gemini:

```powershell
curl.exe -sS -X POST "http://127.0.0.1:8000/v1/responses" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"anthropic:claude-3-5-haiku-20241022\",\"input\":\"Hello\",\"include\":[\"reasoning.encrypted_content\"]}"
```

**Assertions**

- HTTP `400`
- Error body includes `code: "provider_limitation"`
- Error body is explicit and client-visible; there is no silent success with dropped semantics

**Streaming assertions for B1/B2**

- Same transport expectations as (A): `200`, SSE, terminal `response.completed`, `[DONE]`.
- No silent downgrade: if the request uses a feature the projector cannot support, expect a **client-visible** error with `provider_limitation` semantics (HTTP non-2xx and error body per `ResponsesProtocolError` mapping), not a truncated success stream.

## C) Optional legacy OpenAI-style selector cross-check

This is useful if you want to prove the `openai:` route now honors native projected Responses payloads through the same frontend contract.

```powershell
curl.exe -sS -X POST "http://127.0.0.1:8000/v1/responses" ^
  -H "Content-Type: application/json" ^
  -d "{\"model\":\"openai:gpt-4o-mini\",\"input\":[{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"Say hello in one short sentence.\"}]}],\"stream\":true}"
```

**Assertions**

- Frontend behavior matches the same client-facing Responses contract used by `openai-responses:*`
- No lossy failure caused by implicit fallback to `/chat/completions`
- SSE still terminates with canonical terminal event plus `[DONE]`

## D) WebSocket (optional, same frontend path)

1. In `config/config.yaml`, set `responses_api.websocket.frontend_enabled: true` and `responses_api.websocket.backend_enabled: true`.
2. If using the native OpenAI WebSocket path, ensure the backend path is `openai-responses:*` and the OpenAI backend is configured for websocket use as documented in `docs/user_guide/features/websocket-transport.md`.
3. Start the proxy with those settings and connect to `ws://127.0.0.1:8000/v1/responses`.
4. Use the built-in demo script for a copy-paste run:

```powershell
./.venv/Scripts/python.exe scripts/demo_responses_websocket.py --mode proxy --proxy-url ws://127.0.0.1:8000/v1/responses --turns 2
```

5. Or send a raw `response.create` message using your preferred client:

```json
{
  "type": "response.create",
  "model": "openai-responses:gpt-4o-mini",
  "input": "Say hello in one short sentence.",
  "max_output_tokens": 100
}
```

6. **Assertions:** receive JSON events until terminal event, preserve monotonic `sequence_number`, and confirm multi-turn continuity works when the second request sends `previous_response_id` from the first result.

## Evidence to attach when closing task 10.4

- Redacted transcript: HTTP status, model selector, first/last SSE event types, confirmation of `[DONE]`, and backend flavor used.
- For WebSocket: list of received `type` fields through terminal event.
- Note proxy version / git SHA and config flags (`frontend_enabled`, backend types).
- Record whether the translated path used Anthropic, Gemini, or the legacy `openai:` selector.

## Fixture cross-check

After a live run, optionally diff normalized event shapes against:

- `tests/integration/fixtures/responses_api_frontend/http_streaming_sse.json`
- `tests/integration/fixtures/responses_api_frontend/websocket_streaming.json`

Material differences require updating implementation, tests, or spec tasks — not silent edits to fixtures without investigation.
