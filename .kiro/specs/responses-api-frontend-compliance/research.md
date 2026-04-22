# Research: Responses API Frontend Compliance

## 1. Current State Investigation

### Entry Points

| Path | Role |
|------|------|
| `src/core/app/controllers/responses_controller.py` | HTTP POST handler + WebSocket handler |
| `src/core/app/controllers/__init__.py:722` | Routes WebSocket upgrade to `handle_websocket_connection` |
| `src/core/domain/translators/responses/request.py` | Responses → CanonicalChatRequest translation |
| `src/core/domain/translators/responses/wire_stream_emitter.py` | SSE event emission |
| `src/connectors/openai_websocket_client.py` | Upstream OpenAI WebSocket client |
| `src/connectors/openai.py:2136` | OpenAI connector Responses path (HTTP + WS dispatch) |
| `src/core/domain/translators/anthropic/request.py` | Anthropic translation (chat-centric) |
| `src/core/domain/translators/gemini/request.py` | Gemini translation (chat-centric) |
| `src/core/services/translation_service.py` | Translation dispatch |
| `src/core/domain/chat.py` | CanonicalChatRequest — the shared domain model |

### Core Abstraction Mismatch

The entire proxy pipeline is built around `CanonicalChatRequest` (chat completions model).
Responses API requests are translated into this model at the earliest possible point
(`responses_to_domain_request` in `request.py:34`), losing Responses-native structure
before any backend sees it.

This means:
- Typed `input` items are flattened into `messages`
- Tool-call lineage is inferred from chat adjacency, not preserved as Responses items
- `previous_response_id` has no persistent backing — only a per-connection dict
- Streaming output is rebuilt from chat delta chunks, not Responses lifecycle events

---

## 2. Protocol Gaps Identified

### Gap 1: Upstream beta Responses WebSocket `response.create` envelope (CRITICAL — NEEDS VERIFICATION)

**File**: `src/connectors/openai_websocket_client.py:273`

The proxy sends the upstream WS frame as a flat dict with `type: "response.create"` merged
with the payload fields at the top level.

Available source files let us resolve most, but not all, of the ambiguity:

- **HTTP `/responses` requests are flat**. The generated `ResponseCreateParams` model in
  the official SDK defines `model`, `input`, `instructions`, `previous_response_id`, and
  related fields as top-level request keys.
- **Realtime WebSocket `response.create` is nested**. The generated
  `types/beta/realtime/response_create_event.py` model proves the Realtime client event is
  `{"type": "response.create", "response": {...}}`.
- **The specific non-Realtime `/v1/responses` WebSocket mode used by this proxy is not
  represented by a generated SDK type**. Therefore, the available source files do not prove
  whether that particular upstream surface expects flat or nested framing.
- **OpenCode provides corroborating evidence for HTTP Responses streaming only**. It models
  the `ResponseStreamEvent`-style HTTP event family (`response.completed`, `response.incomplete`,
  `error`, etc.), but it does not implement or document the beta `/v1/responses` WebSocket mode.

**Action required before implementing task 1**: Verify the exact expected frame shape
against the live `/v1/responses` WebSocket endpoint used by the proxy. The fix must be
validated against actual API behavior, not inferred from HTTP `/responses`, Realtime,
or OpenCode's HTTP streaming implementation.

### Gap 2: Connection-local `previous_response_id` cache (CRITICAL)

**File**: `src/core/app/controllers/responses_controller.py:1571`

`response_cache` is a plain `dict` scoped to a single WebSocket connection lifetime.
The Responses API contract implies that `previous_response_id` references a server-side
stored response object that persists across connections, reconnects, and process restarts.

Current behavior:
- Any reconnect loses all cached response ids
- Multi-process deployments cannot share the cache
- The proxy rejects valid `previous_response_id` values it has not seen in this connection

### Gap 3: Lossy input/output item translation (HIGH)

**File**: `src/core/domain/translators/responses/request.py:45-52`

`input` is immediately converted to `messages` if `messages` is absent. This loses:
- Item type metadata (`message`, `function_call`, `function_call_output`, `reasoning`)
- Item-level `id` fields needed for tool-call linkage
- Multi-part content structure within items
- Ordering guarantees for mixed item types

### Gap 4: Non-standard SSE event lifecycle (HIGH)

**File**: `src/core/domain/translators/responses/wire_stream_emitter.py`

The emitter invents proxy-specific event names and ordering. The official Responses API
SSE lifecycle is:

```
response.created              (sequence_number: 0)
response.in_progress          (sequence_number: 1)
response.output_item.added    (output_index, item)
response.content_part.added   (output_index, content_index, part)
response.output_text.delta    (output_index, content_index, delta)
response.output_text.done     (output_index, content_index, text)
response.content_part.done    (output_index, content_index, part)
response.output_item.done     (output_index, item)
response.completed / response.failed / response.incomplete
[DONE]  (HTTP SSE only — verify per transport)
```

**Important**: `sequence_number` is a **required** field on all streaming events per the
official reference. It must be a monotonically increasing integer starting at 0 for each
response stream. The proxy must emit it on every event frame.

The current emitter:
- Emits `response.delta` (non-standard)
- Emits `response.completed` as terminal without guaranteed `response.done` follow-up
- Does not emit `response.created`, `response.in_progress`, `response.output_item.added`,
  `response.content_part.added`
- Uses proxy-local `sequence_number` values inconsistently (should be per-stream monotonic)
- Uses `item_index`/`part_index` instead of official `output_index`/`content_index`

### Gap 5: WebSocket frontend emits the wrong event family (HIGH)

**File**: `src/core/app/controllers/responses_controller.py:1778-1820`

The WS handler emits:
- `response.delta` (non-standard passthrough)
- `response.content_part.delta` (non-standard)
- `response.done` (a Realtime-style terminal event, not part of the typed HTTP
  `ResponseStreamEvent` union)

It never emits the typed Responses lifecycle preamble events. Unless live verification
proves that the beta `/v1/responses` WebSocket surface intentionally differs from HTTP
Responses streaming, the proxy should default to the typed `ResponseStreamEvent` family
used by the official SDK and corroborated by OpenCode.

### Gap 6: Backend translation loses Responses semantics (MEDIUM)

**Files**: `src/core/domain/translators/anthropic/request.py:141`,
`src/core/domain/translators/gemini/request.py:98`

Both translators operate on `CanonicalChatRequest.messages`. By the time they run,
Responses-native item structure is already gone. This means:
- Tool-call items cannot be faithfully round-tripped
- Function call outputs are inferred from message adjacency
- Multi-part content is partially reconstructed

### Gap 7: No explicit provider limitation disclosure (MEDIUM)

When Anthropic/Gemini cannot represent a Responses feature (e.g., reasoning items,
`previous_response_id` linkage), the proxy silently degrades without surfacing a
contract-compatible error or limitation to the client.

---

## 3. Architecture Decisions

### Decision 1: Introduce a first-class Responses domain model

**Rationale**: The root cause of all gaps is the premature flattening of Responses
requests into `CanonicalChatRequest`. A `ResponsesDomainRequest` that preserves typed
items must be introduced and kept alive through the pipeline until the provider boundary.

**Trade-off**: Requires new translation paths for each backend. Existing chat paths
are unaffected.

### Decision 2: Persistent session store for `previous_response_id`

**Rationale**: The contract implies server-side response history. The simplest
compliant implementation is a proxy-managed in-process store (SQLite or in-memory with
TTL) keyed by response id. For single-process deployments this is sufficient. For
multi-process, an external store (Redis/DB) can be plugged in later via interface.

**Trade-off**: Adds a storage dependency. Scoped to Responses API only.

### Decision 3: Unified Responses event state machine

**Rationale**: HTTP SSE and WebSocket frontends should share one semantic event pipeline,
but terminal behavior must remain transport-correct. For HTTP `/responses` SSE, the
official SDK-typed completion event is `response.completed` and the shared SSE decoder
expects a trailing `[DONE]` sentinel. `response.done` is typed in the Realtime API,
not the HTTP `ResponseStreamEvent` union. A single `ResponsesWireRenderer` driven by a
`ResponsesEventNormalizer` ensures consistency while preserving those transport-specific
differences.

**Trade-off**: Requires refactoring `wire_stream_emitter.py` and the WS handler loop,
plus a transport matrix so implementers do not conflate HTTP Responses streaming with
Realtime events.

### Decision 4: Verify upstream WS envelope before patching

**Rationale**: The installed official SDK proves that Realtime `response.create` uses a
nested `response` object, but it does not provide a separate typed non-Realtime Responses
WebSocket client event. The proxy must therefore verify the exact expected upstream shape
for its `/v1/responses` WebSocket path before changing behavior. Task 1 remains first,
but it starts with verification rather than an assumed one-line fix.

### Decision 5: Per-provider backend projector

**Rationale**: Each backend (OpenAI native, Anthropic, Gemini) needs its own
projection from `ResponsesDomainRequest` to its wire format. This replaces the
current single `responses_to_domain_request` → `CanonicalChatRequest` path.

---

## 4. External References

- OpenAI Responses API SSE event reference (platform.openai.com/docs/api-reference/responses)
- OpenAI Responses WebSocket protocol (wss://api.openai.com/v1/responses)
- Anthropic Messages API (docs.anthropic.com/en/api/messages)
- Gemini generateContent API (ai.google.dev/api/generate-content)
- EARS requirements format (.kiro/settings/rules/ears-format.md)
