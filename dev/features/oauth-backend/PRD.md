# OpenAI OAuth Backend (Codex) – PRD

## 1. Background & Goals

The `openai-oauth` backend predicates on the unofficial ChatGPT/Codex Responses API. The current connector evolved to make KiloCode work, but it has ad-hoc prompt injections and format rewrites that break other clients. We need a definitive specification that:

1. Supports **pure pass-through** when the client already speaks OpenAI Responses (e.g., Codex CLI).
2. Provides **compatibility layers** for other client protocols (Chat Completions, legacy tool messages, textual tool calls) while using generic abstractions instead of client-specific hacks.
3. Ensures **tool call translations** preserve the canonical `tool_calls` structure while optionally rendering textual representations driven by capability flags (e.g., XML renderer) rather than bespoke agent logic.
4. Keeps **prompt/tool schema** configurable; inject the codex defaults only when required by the backend, and otherwise allow client-provided prompts/tool schemas to pass through.
5. Maintains **observability and diagnostics** (wire capture, logging) appropriate for a proof-of-concept; advanced telemetry can follow later.

## 2. Personas & Use Cases

### Personas

- **CLI Engineer**: runs codex-cli (official OpenAI client). Expects zero proxy interference.
- **Custom Agent Developer**: builds agents like KiloCode, Droid, etc., that may speak different frontend protocols or expect tool calls embedded in text.
- **Infra Operator**: deploys the proxy and configures backend credentials. Needs clarity on what knobs exist to adjust translations/prompts.

### Core Use Cases

1. **Codex CLI passthrough** – proxy should forward requests/responses unchanged.
2. **Chat Completion clients** – clients using the standard OpenAI Chat API interface should be translated into Responses API requests.
3. **Tool-call text rendering** – agents that expect textual tool call encoding (e.g., XML blocks) should get them without losing canonical metadata, with rendering driven by generic capability settings.
4. **Custom prompts** – allow operators or clients to provide their own system prompt and tool schema (only inject codex defaults when explicitly required).
5. **Mixed traffic** – different clients (codex, Droid, OpenCode, etc.) can hit the proxy simultaneously, each receiving translation based on capability descriptors rather than hard-coded client rules.

## 3. Functional Requirements

### 3.1 Frontend Request Handling

1. Accept both **OpenAI Chat** (`/v1/chat/completions`) and **OpenAI Responses** (`/v1/responses`) style requests.
2. Each incoming request must be normalized into a **CanonicalChatRequest**.
3. Augment request metadata with **client capabilities**, either inferred (headers, agent-specific markers) or user-configured.

### 3.2 Backend Request Generation (Codex Responses API)

1. When the input is native Responses (and marked for passthrough), **forward** without rebuilding.
2. Otherwise, construct a **Codex-compliant payload**:
   - Include required fields: `model`, `input` array, `tools`, `session_id`, etc.
   - Inject tool definitions. Allow overrides or merging of custom tool schemas.
   - Allow customizing the **system prompt block** while ensuring minimal codex guardrails/constraints remain (tool names, safety disclaimers).
   - Support optional headers: `conversation_id`, `session_id`, etc.
3. Provide configuration toggles:
   - `codex_passthrough`: globally enable/disable passthrough mode.
   - `tool_schema_mode`: choose between `use_default`, `merge_custom`, `custom_only`.
   - `prompt_mode`: `codex_default`, `merge_custom`, `custom_only`.
4. Preserve **auth handling** (load tokens/auth.json, refresh watchers).

### 3.3 Streaming & Response Translation

1. Always maintain canonical `tool_calls` metadata in the streamed deltas.
2. Introduce a **tool text renderer** layer driven by capability descriptors:
   - `none` (no extra text, pure canonical).
   - Generic renderers (e.g., XML, Markdown) referenced by capability keys.
   - Custom renderer modules registered via configuration.
3. Renderer must be capability-driven; unknown tools should fall back to a generic textual summary rather than agent-specific logic.
4. Guarantee the streaming pipeline remains asynchronous, non-blocking, and integrates with wire capture.

### 3.4 Diagnostics & Observability

1. Expose logs that clearly state when requests are passthrough vs translated.
2. Log applied prompt/tool schema mode for each request (debug-level).
3. Wire capture should capture both raw upstream and final downstream payloads when enabled.
4. Provide metrics/counters (if infrastructure exists) for translation paths.

## 4. Non-Functional Requirements

1. Performance: translation layers should not significantly increase latency (<5% overhead in typical flows).
2. Reliability: must recover gracefully when client/subsystem misbehaves (e.g., fallback to canonical tool text if renderer throws).
3. Extensibility: allow new capability profiles/renderers without modifying core translation logic or introducing agent-specific branches.
4. Security: do not expose OAuth tokens in logs or responses; ensure prompt overrides cannot remove baseline safety instructions unless explicitly configured.

## 5. Architecture Overview

### 5.1 Layered Design

```plaintext
Incoming HTTP → Frontend Adapter → Canonical Domain → Backend Adapter → Codex Responses
                               ↑             ↓
               Capability Resolver ─┐   Stream Adapter ← Upstream SSE
                                    └→ Tool Text Renderer Registry
```

- **Frontend Adapter**: converts chat/Responses/other protocols to domain model.
- **Client Capability Resolver**: deduces capability flags from request metadata or config (e.g., `tool_text_format`, `prompt_mode`).
- **Backend Adapter**: builds codex payload when needed; bypasses when passthrough.
- **Stream Adapter**: converts codex SSE to canonical stream; attaches renderer output based on resolved capabilities.
- **Tool Text Renderer Registry**: maps capability keys to renderer implementations (generic XML/Markdown/etc.).

### 5.2 Configuration Matrix

| Capability Flag | Description | Default |
|-----------------|-------------|---------|
| `codex_passthrough` | If true, forward native Responses requests untouched | true when request exactly matches codex schema |
| `prompt_mode` | `codex_default` / `merge_custom` / `custom_only` | `codex_default` |
| `tool_schema_mode` | `use_default` / `merge_custom` / `custom_only` | `use_default` |
| `tool_text_renderer` | Renderer key (e.g., `none`, `xml`, `markdown`) or custom module path | `none` |
| `fallback_tool_renderer` | Template for unsupported tools | `[Tool ${name}] ${json arguments}` |

Provide runtime overrides via environment variables, config, or per-session metadata.

## 6. Translation & Rendering Rules

### 6.1 Request Translation

1. **Detect native codex payloads** by:
   - Checking `input` array structure (messages with `type`: `input_text`, etc).
   - Looking for the canonical codex instructions/tool schema or a client-provided capability flag that asserts passthrough.
   - Supporting explicit opt-in via `extra_body.codex_passthrough == true`.
2. Maintain original request when passthrough is flagged.
3. Otherwise:
   - Build codex system instructions only when required by configuration; otherwise pass through client-provided prompts.
   - Create `input` items: user instructions, environmental context, chat history, etc.
   - Insert tool definitions via schema provider (default/merged/custom).

### 6.2 Response Translation

1. Map codex SSE events to canonical domain:
   - `response.output_text.delta` → `choices[0].delta.content`.
   - `response.function_call_arguments.delta` → incremental tool_calls.
   - `response.function_call_arguments.done` → finalize tool call + optional text renderer.
2. Pass tool_call metadata through unchanged.
3. Invoke tool text renderer when configured:
   - Example (XML renderer):
        - `shell` tool → `<execute_command><command>...</command></execute_command>`
        - `apply_patch` tool → `<apply_diff><path>...</path><diff>...</diff></apply_diff>`
        - `view_image` → `<view_image><path>...</path></view_image>`
   - Ensure renderer is pure function: `render(tool_call, metadata, raw_arguments) -> str | None`.
   - Renderer Interface Contract:
      - Input: `tool_call` (dict with `id`, `type`, `function`), `metadata` (dict with context), `raw_arguments` (str JSON).
      - Output: Rendered text string or `None` (no text overlay).
      - Error Handling: Renderers must not throw exceptions; return `None` and log warnings internally.
      - Thread Safety: Renderers should be stateless and thread-safe.
4. When renderer returns text, set both `_tool_call_text` and `delta.content` to that value for convenience; clients that ignore text still rely on `tool_calls`.
5. Provide fallback textual summary if renderer missing and config enables it (avoid empty assistant response).

## 7. Prompt & Tool Schema Management

1. Maintain a **minimal Codex schema package** (tools + guardrails) that can be injected only when the backend requires it; otherwise rely on client-provided prompts.
2. Provide extension points:
   - Append additional tools to the schema (with validation).
   - Replace the entire schema (but warn about compatibility).
3. For prompts:
   - `codex_default`: use built-in prompt.
   - `merge_custom`: append/prepend custom text.
   - `custom_only`: use supplied prompt verbatim but warn that operator is responsible for exposing codex tool instructions.
4. Document interplay between prompts, tools, and renderers to avoid drift.

## 8. Client Capability Detection

1. Discover capabilities via:
   - Header `X-Client-Capabilities`.
   - Request body field `extra_body.client_capabilities`.
   - Configuration defaults or server-side mapping by API key/session.
2. Capability structure example:

```json
{
  "protocol": "openai-chat",
  "tool_text_format": "xml",
  "codex_passthrough": false
}
```

3. Resolve precedence: request metadata > session config > global config > defaults.
4. Existing detectors (e.g., Cline/Kilo forks) may seed default capability values, but translation logic must rely on the generic capability abstraction rather than branching on client identities.

### 8.1 Capability Flag Definitions

- `codex_passthrough`: Boolean. If true, forward native Responses requests untouched when they match codex schema.
- `prompt_mode`: Enum (`codex_default`, `merge_custom`, `custom_only`). Controls system prompt injection behavior.
- `tool_schema_mode`: Enum (`use_default`, `merge_custom`, `custom_only`). Controls tool definitions provided to backend.
- `tool_text_renderer`: String. Renderer key (e.g., `none`, `xml`, `markdown`) or custom module path for textual tool call representation.
- `fallback_tool_renderer`: String template for unsupported tools (e.g., `[Tool ${name}] ${json arguments}`).

### 8.2 Capability Structure Example

```json
{
  "protocol": "openai-chat",
  "tool_text_format": "xml",
  "codex_passthrough": false,
  "prompt_mode": "codex_default",
  "tool_schema_mode": "use_default",
  "tool_text_renderer": "xml",
  "fallback_tool_renderer": "[Tool ${name}] ${arguments}"
}
```

## 9. Error Handling & Fallbacks

1. If translator fails to parse upstream chunk, emit diagnostic chunk and continue when possible.
2. If renderer throws, log warning and continue without text overlay.
3. If passthrough detection misfires (e.g., partial codex payload), fall back to translation path but log mismatch.
4. Preserve ability to respond with HTTP errors if backend returns 4xx/5xx, including raw error detail.

## 10. Implementation Plan (High Level)

1. **Refactor connector** into distinct adapters (front-end, backend, stream).
2. **Introduce capability registry** and configuration.
3. **Implement renderer interface** with built-in strategies (`none`, `xml`, `markdown`, etc.) that are reusable and capability-driven.
4. **Add passthrough detection and toggles**.
5. **Update tests**:

- Unit tests for translators/renderers (including XML renderer and tool fallback behaviors).
- Integration tests simulating codex CLI passthrough plus generic agents (e.g., Chat Completion clients, Droid/OpenCode-style tool usage).
  - Specific test file updates: `tests/unit/connectors/test_openai_oauth_codex.py` (payload construction), `tests/unit/core/services/test_translation_service_responses_api.py` (streaming translations), and new tests for capability resolver and renderer registry.

6. **Documentation**: update README/config docs to explain capability flags and prompt/tool overrides.

## 11. Open Questions / Future Enhancements

1. What is the minimal prompt/tool schema required to keep the codex backend functional when clients provide their own instructions?
2. How should we model capability descriptors so generic agents (Droid, OpenCode, etc.) work out-of-the-box without per-client branches?
3. When should we introduce advanced features (rate limiting, detailed metrics, adaptive renderers) beyond the proof-of-concept scope?

## 12. Acceptance Criteria

- Codex CLI requests remain byte-identical when `codex_passthrough=true`.
- Chat Completion clients receive valid Responses API payloads and tool calls.
- Capability-driven renderer can produce `<execute_command>` / `<apply_diff>` / `<view_image>` style output (or other formats) when configured, while canonical tool metadata remains intact.
- Custom prompt/tool schema overrides documented and verified via tests.
- All existing regression tests pass; new coverage for renderer and passthrough added.
- Logging shows clear indication of translation path vs passthrough.

---
