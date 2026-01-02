# OpenAI Codex Connector (Unofficial) — Execution Agent Instructions

This document is an execution checklist for hardening the `openai-codex` backend connector for “enthusiast / vibe coder” usage:

- Expectation: **best-effort**, “works until OpenAI changes it”, not “stable API contract”.
- Goal: behave like a **transparent proxy to Codex** with **client-owned tool calling** by default.
- Non-goal: full Codex CLI parity or long-term upstream stability guarantees.

Repository constraints (do not ignore):
- Always use `./.venv/Scripts/python.exe` (Windows).
- Do not `pip install`; update `pyproject.toml` only if deps change.
- After editing Python files, run `ruff` + `black` + `mypy` on changed files, then run relevant `pytest`.

---

## 1) Desired Default Behavior (Enthusiast Mode)

When a random agent/client (Factory Droid / OpenCode / etc.) uses this proxy with the Codex backend:

1. **Tools are client-supplied**:
   - The proxy should not inject Codex CLI built-in tools (`apply_patch`, `shell`, etc.) unless the operator explicitly opts in.
2. **Tools are client-executed**:
   - The proxy should not run tool-call reactor/tool execution by default for this backend.
3. **No environment leakage**:
   - The proxy should not inject `<environment_context>` blocks by default.
4. **Prompt robustness**:
   - The connector should avoid sending custom `instructions` that can trigger `400 {"detail":"Instructions are not valid"}`.
5. **Still functional**:
   - Basic text-only request succeeds (streaming or non-stream) via `openai-codex` and returns assistant text.

---

## 2) Recommended Capability Profiles (Exact Overrides)

Capabilities are resolved via `CodexCapabilityResolver` and can be supplied:
- Per request: request JSON `extra_body.codex_capabilities` (or `extra_body.client_capabilities`)
- Globally (operator): `config/config.yaml` under `backends.openai_codex.extra.codex.default_capabilities`
- Globally (operator): env var `OPENAI_CODEX_DEFAULT_CAPABILITIES` as JSON

Capability fields (current set): `src/connectors/_openai_codex_capabilities.py`.

### Profile A — “Enthusiast / Chat Completions client”
Use this when clients call the proxy via `/v1/chat/completions` and use standard OpenAI tool calling.

Recommended `codex_capabilities`:
```json
{
  "protocol": "openai-chat",
  "codex_passthrough": false,
  "prompt_mode": "codex_default",
  "tool_schema_mode": "custom_only",
  "tool_text_format": "none",
  "bypass_tool_call_reactor": true,
  "include_environment_context": false
}
```

Notes:
- `tool_schema_mode="custom_only"` ensures only client `tools` are sent.
- `bypass_tool_call_reactor=true` prevents server-side tool execution interception.
- `include_environment_context=false` avoids leaking local info.
- `prompt_mode="codex_default"` minimizes `instructions` validation failures; client “system prompt” is treated as user-level `<user_instructions>` (see `src/connectors/_openai_codex_request_translator.py`).

### Profile B — “Enthusiast / Responses API client” (best fidelity)
Use this when clients can call the proxy via `/v1/responses` (preferred for Codex).

Recommended `codex_capabilities`:
```json
{
  "protocol": "openai-responses",
  "codex_passthrough": true,
  "prompt_mode": "codex_default",
  "tool_schema_mode": "custom_only",
  "tool_text_format": "none",
  "bypass_tool_call_reactor": true,
  "include_environment_context": false
}
```

Notes:
- `codex_passthrough=true` aims to preserve client-provided Responses `input` semantics where the pipeline supports it.
- Prefer this profile if the client wants Responses-style content parts, tool schemas, and streaming events.

### Profile C — “Compatibility / VTC or XML clients (Kilo/Cline-style)”
This is explicitly opt-in and not the default enthusiast path.

Recommended:
```json
{
  "protocol": "openai-chat",
  "codex_passthrough": false,
  "prompt_mode": "codex_default",
  "tool_schema_mode": "codex_default",
  "tool_text_format": "codex_xml",
  "bypass_tool_call_reactor": false,
  "include_environment_context": true
}
```

Operator must also enable the compatibility layer (see `config/backends/openai_codex/backend.yaml`).

---

## 3) Where to Surface These Settings (Operator vs Client)

### 3.1 Operator defaults (`config/config.yaml`)
Add/modify:
```yaml
backends:
  openai_codex:
    timeout: 120
    extra:
      codex:
        default_capabilities:
          protocol: openai-chat
          prompt_mode: codex_default
          tool_schema_mode: custom_only
          tool_text_format: none
          bypass_tool_call_reactor: true
          include_environment_context: false
          codex_passthrough: false
```

Rationale:
- `config/backends/openai_codex/backend.yaml` is validated against `config/schemas/openai_codex_backend.schema.yaml` and does **not** include the `extra.codex` namespace used by the connector’s `SettingsLoader`.
- The connector reads these values from `app_config.backends.openai_codex.extra.codex.*` (see `src/connectors/openai_codex/settings.py`).

### 3.2 Operator env var (simple override)
Set:
```bash
OPENAI_CODEX_DEFAULT_CAPABILITIES='{"tool_schema_mode":"custom_only","bypass_tool_call_reactor":true,"include_environment_context":false,"prompt_mode":"codex_default","protocol":"openai-chat"}'
```

### 3.3 Per-request override (client)
Chat Completions example:
```json
{
  "model": "openai-codex:gpt-5.1-codex",
  "messages": [{"role": "user", "content": "Hello"}],
  "tools": [{"type":"function","function":{"name":"my_tool","parameters":{"type":"object"}}}],
  "extra_body": {
    "codex_capabilities": {
      "tool_schema_mode": "custom_only",
      "bypass_tool_call_reactor": true,
      "include_environment_context": false
    }
  }
}
```

Responses example:
```json
{
  "model": "openai-codex:gpt-5.1-codex",
  "input": [{"type":"message","role":"user","content":[{"type":"input_text","text":"Hello"}]}],
  "tools": [{"type":"function","function":{"name":"my_tool","parameters":{"type":"object"}}}],
  "extra_body": {
    "codex_capabilities": {
      "protocol": "openai-responses",
      "codex_passthrough": true,
      "tool_schema_mode": "custom_only",
      "bypass_tool_call_reactor": true,
      "include_environment_context": false
    }
  }
}
```

---

## 4) Execution Plan (What to Fix / Implement)

### Task 1 — Change defaults to “client tools only + no server-side tool execution”
Scope:
- `src/connectors/openai_codex/settings.py` (SettingsLoader defaults)
- `tests/unit/connectors/openai_codex/test_settings.py` (default assertions)
- Any other tests comparing against `CodexClientCapabilities()` defaults

Required default capability changes:
- Ensure `default_capabilities.tool_schema_mode = "custom_only"` (already done in current repo state).
- Set `default_capabilities.bypass_tool_call_reactor = True`.
- Set `default_capabilities.include_environment_context = False`.

Acceptance criteria:
- With no extra config and no per-request overrides:
  - Client `tools` are forwarded as-is.
  - No built-in Codex tools are added.
  - The tool-call reactor does not execute or mutate tool calls.
  - No environment context message is injected.

### Task 2 — Make `tool_schema.base_tools` actually work
Problem:
- `SettingsLoader` supports `tool_schema.base_tools`, but `ToolSchemaResolver` currently ignores it and always uses its hardcoded built-ins.

Scope:
- `src/connectors/openai_codex/tool_schema.py`

Implementation:
- In `_get_default_tools()`:
  - If `settings.tool_schema["base_tools"]` is a list (including empty list), use it as the base tool list.
  - Else fall back to current built-ins.

Acceptance criteria:
- If operator sets `base_tools: []`, then `tool_schema_mode="codex_default"` yields no tools.
- If operator sets `base_tools: [...]`, then `codex_default` yields exactly those tools.
- `merge_custom` merges base tools + request tools (collision rules preserved).

### Task 3 — Make prompt handling robust against “Instructions are not valid”
Observed failure mode:
- Sending altered Codex `instructions` can fail with `400 {"detail":"Instructions are not valid"}`.

Scope:
- `src/connectors/openai_codex/payload.py`
- `src/connectors/_openai_codex_request_translator.py`
- Potentially: `src/connectors/_openai_codex_connector.py` (enforcement / error shaping)

Recommended policy (implement):
- Always send Codex default `instructions`.
- Treat client “system prompts” as user-level `<user_instructions>` blocks (as a user message), never as `instructions`.
- If a request explicitly tries to set `prompt_mode != "codex_default"`, either:
  - hard-force it back to `codex_default`, or
  - reject with a clear error message explaining why.

Acceptance criteria:
- A request containing a `system` message does not break by default.
- If backend rejects prompt changes, the returned error is actionable (explains which knob to change).

### Task 4 — Document the intended usage for enthusiasts
Scope:
- `config/config.example.yaml` (add `backends.openai_codex.extra.codex.default_capabilities` example)
- `docs/` or `README.md` (short section: “Using Codex backend with third-party agents”)
- `config/backends/openai_codex/backend.example.yaml` (clarify it is for compatibility layer + limits only; capabilities live in `config/config.yaml`)

Acceptance criteria:
- A new user can configure “Profile A” by copying one YAML block.
- Docs explain when to use `/v1/responses` vs `/v1/chat/completions`.

### Task 5 — Verify with POC + tests (must run)
POC (already exists):
- `dev/scripts/poc_openai_codex_connector.py`

Commands:
- Format + typecheck changed files:
  - `./.venv/Scripts/python.exe -m ruff check --fix <files>`
  - `./.venv/Scripts/python.exe -m black <files>`
  - `./.venv/Scripts/python.exe -m mypy <files>`
- Focused tests:
  - `./.venv/Scripts/python.exe -m pytest tests/unit/connectors/openai_codex -q`
- Run POC:
  - `./.venv/Scripts/python.exe dev/scripts/poc_openai_codex_connector.py --message "Reply exactly with: OK"`

Acceptance criteria:
- Tests above are green.
- POC prints `OK` (or equivalent expected output).

---

## 5) Guardrails / Common Pitfalls

- Do not assume Chat Completions tool schemas are identical to Codex custom tools:
  - Some Codex “custom” tools must omit `parameters`; ensure schemas match what Codex accepts.
- If you see `choices[0].message.content: null` on non-streaming:
  - Check stream chunk types; accumulation must handle Pydantic stream chunk models via `.model_dump()`.
- Backend will always stream SSE internally:
  - Non-stream client requests must accumulate stream into one response (already implemented).

---

## 6) Deliverables Checklist

1. Defaults updated (`bypass_tool_call_reactor=true`, `include_environment_context=false`) in `SettingsLoader`.
2. `tool_schema.base_tools` wired into `ToolSchemaResolver`.
3. Prompt robustness policy enforced; clear error mapping for prompt rejection.
4. Documentation updates with copy-paste config snippets (Profiles A/B).
5. Tests + POC run with recorded command outputs in the PR description / execution notes.

