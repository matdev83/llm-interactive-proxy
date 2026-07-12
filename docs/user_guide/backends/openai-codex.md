# OpenAI Codex Backend

The OpenAI Codex backend connector is a specialized integration designed to route requests through the OpenAI Codex / Responses API infrastructure using OAuth tokens. It mimics the authentication and request patterns of the Codex CLI to facilitate development and compatibility testing.

## History context compaction

When **history context compaction** is enabled server-wide (`compaction` / `--enable-context-compaction`; see [Context Compaction](../features/context-compaction.md)), the proxy applies an extra **session-level** rule for this backend:

- The **first** time a request in a given **session** is routed to **`openai-codex`** (any instance in the `openai-codex` family, e.g. `openai-codex:…` or weighted `openai-codex.N`), history compaction is **turned off for the rest of that session** and stored in session state.
- The operator sees **one** warning log line for that session when the switch happens; later requests do not repeat it.
- **Dynamic tool-output compression** is not part of this rule and keeps following its own config.

If you rely on compaction for long mixed-backend sessions, plan for **Codex turns** to permanently disable **history** compaction for that session once Codex is used.

## Configuration

To use the OpenAI Codex backend, you can configure it via environment variables or the `config.yaml` file.

### Basic Configuration

**YAML:**
```yaml
backends:
  openai_codex:
    type: openai-codex
```

**Environment Variables:**
- `OPENAI_API_BASE_URL`: Override for the API base URL.
- `OPENAI_CODEX_MANAGED_OAUTH_ENABLED`: Enable/disable managed OAuth accounts (`true`/`false`).
- `OPENAI_CODEX_MANAGED_OAUTH_STORAGE_PATH`: Directory with managed account JSON files.
- `OPENAI_CODEX_MANAGED_OAUTH_ACCOUNTS`: `"all"` or JSON array of allowed account ids.
- `OPENAI_CODEX_MANAGED_OAUTH_SELECTION_STRATEGY`: `round-robin`, `random`, `first-available`, `session-affinity`.
- `OPENAI_CODEX_MANAGED_OAUTH_ALLOW_LEGACY_FALLBACK`: Allow fallback to `auth.json` when no managed accounts are configured.
- `OPENAI_CODEX_PATH`: Optional legacy fallback directory containing `auth.json`.

### Supported models and reasoning effort

The `openai-codex`, `openai-codex-v2` and `openai-codex-app-server` connectors
share **one auto-discovered model catalog** — no model slugs are hardcoded in
the connector code.

**Auto-discovery at startup.** On proxy startup the `CodexModelCatalogStage`
runs `codex debug models` (via the resolved Codex CLI binary) and parses the
result into the catalog used by all three Codex variants. If discovery fails
(binary missing, timeout, non-zero exit, malformed output) or is disabled, the
proxy falls back to a **shipped snapshot** at
`src/resources/codex/codex_model_catalog.json` (the verbatim `codex debug
models` output). Operators can override the fallback file via
`extra.codex.model_catalog.fallback_path`.

The catalog is the verbatim `codex debug models` output, so it contains exactly
the models the installed Codex CLI advertises (e.g. Codex CLI `0.144.0` reports
`gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `gpt-5.5`, `gpt-5.4`,
`gpt-5.4-mini` as routable, plus CLI-only `gpt-5.3-codex-spark` and hidden
`codex-auto-review` which are **not** routable). The app-server variant
additionally advertises the `auto` routing sentinel (the app-server resolves
the actual model server-side).

> **Backward-incompatible:** legacy Codex slugs that the Codex CLI no longer
> advertises (e.g. `gpt-5.1-codex`, `gpt-5-codex`, `gpt-5.3-codex`,
> `gpt-oss-120b`, ...) are **no longer routable**. To keep routing them, ship a
> custom fallback JSON (same `codex debug models` format) and point
> `extra.codex.model_catalog.fallback_path` at it.

**Reasoning effort hierarchy** (lowest → highest depth, derived from the
discovered catalog):

`low` < `medium` < `high` < `xhigh` < `max` < `ultra`

Requesting an effort level a model does not support automatically downgrades to
the highest supported level at or below the request (e.g. `ultra` → `max` on
`gpt-5.6-luna`, `max`/`ultra` → `xhigh` on `gpt-5.5`, `xhigh` → `high` on
unknown models). The app-server applies the same per-model clamping for non-
`auto` models; `auto` passes the validated effort through to the app-server.

### Output verbosity

GPT-5 family models accept an output verbosity hint (`low` / `medium` / `high`).
Set it via backend config or URI query parameters:

```yaml
backends:
  openai_codex:
    extra:
      verbosity: low
```

```text
openai-codex:gpt-5.4-mini?reasoning_effort=high&verbosity=low
```

Wire shapes:

- `openai-codex` / `openai-codex-v2`: Responses payload `"text": {"verbosity": "..."}` (omitted when unset or when the catalog reports `support_verbosity: false` for the model)
- `openai-codex-app-server`: process spawn override `-c model_verbosity=...` (Codex `turn/start` has no verbosity field). If a later request asks for a different verbosity while the app-server process is still alive, the connector restarts that process before the next turn

**Configuration** (`extra.codex.model_catalog`):

```yaml
backends:
  openai_codex:
    extra:
      codex:
        model_catalog:
          discovery_enabled: true            # run `codex debug models` at startup
          # fallback_path: /etc/codex/catalog.json   # override shipped snapshot
          # codex_binary_path: /usr/local/bin/codex   # explicit binary path
          discovery_timeout_seconds: 10.0
```

**Inspecting / refreshing the catalog:**

```powershell
# Print the shipped fallback catalog (slugs, per-model reasoning levels, downgrade matrix)
./.venv/Scripts/python.exe scripts/list_codex_models.py
./.venv/Scripts/python.exe scripts/list_codex_models.py --json

# Refresh the shipped snapshot from the installed Codex CLI
./.venv/Scripts/python.exe scripts/refresh_codex_model_catalog.py
```

### Authentication

The connector now uses a **managed multi-account OAuth store first**, and only falls back to legacy Codex CLI credentials when needed.

1. **Managed account mode (preferred)**  
   Accounts are stored as individual JSON files (default: `var/openai_codex_oauth_accounts`) and selected by strategy (`round-robin`, `session-affinity`, etc.).
2. **Legacy fallback mode**  
   If managed OAuth is enabled but there are no configured managed accounts, the connector can still read:
   - Windows: `%USERPROFILE%\.codex\auth.json`
   - Cross-platform: `~/.codex/auth.json`

#### Managed OAuth configuration example

```yaml
backends:
  openai_codex:
    timeout: 120
    extra:
      codex:
        managed_oauth:
          enabled: true
          storage_path: var/openai_codex_oauth_accounts
          accounts: all
          selection_strategy: round-robin
          refresh_buffer_seconds: 300
          session_affinity_ttl_seconds: 86400
          session_affinity_max_entries: 10000
          allow_legacy_fallback: true
```

#### Account management script

Use the built-in script to add/list/re-authorize/remove managed OpenAI Codex accounts:

```powershell
./.venv/Scripts/python.exe scripts/manage_openai_codex_accounts.py list
./.venv/Scripts/python.exe scripts/manage_openai_codex_accounts.py add
./.venv/Scripts/python.exe scripts/manage_openai_codex_accounts.py show <account_id>
./.venv/Scripts/python.exe scripts/manage_openai_codex_accounts.py update <account_id>
./.venv/Scripts/python.exe scripts/manage_openai_codex_accounts.py remove <account_id>
```

### Enthusiast Mode Configuration (Third-Party Agents)

When using the Codex backend with third-party agents (Factory Droid, OpenCode, etc.), the connector defaults to "enthusiast mode" which behaves as a transparent proxy:

- **Client tools only**: Only tools supplied by the client are forwarded (no built-in Codex tools injected)
- **No server-side execution**: Tool calls are returned to the client for execution
- **No environment leakage**: Environment context is not injected by default
- **Robust prompt handling**: Uses Codex default instructions to avoid validation errors

#### Profile A: Chat Completions Client

For clients using `/v1/chat/completions`:

```yaml
backends:
  openai_codex:
    timeout: 120
    extra:
      codex:
        default_capabilities:
          protocol: openai-chat
          codex_passthrough: false
          prompt_mode: codex_default
          tool_schema_mode: custom_only
          tool_text_format: none
          bypass_tool_call_reactor: true
          include_environment_context: false
```

#### Profile B: Responses API Client (Best Fidelity)

For clients using `/v1/responses` (preferred for Codex):

```yaml
backends:
  openai_codex:
    timeout: 120
    extra:
      codex:
        default_capabilities:
          protocol: openai-responses
          codex_passthrough: true
          prompt_mode: codex_default
          tool_schema_mode: custom_only
          tool_text_format: none
          bypass_tool_call_reactor: true
          include_environment_context: false
```

#### Per-Request Overrides

You can also override capabilities per-request via `extra_body`:

```json
{
  "model": "openai-codex:gpt-5.1-codex",
  "messages": [{"role": "user", "content": "Hello"}],
  "tools": [{"type": "function", "function": {"name": "my_tool", "parameters": {}}}],
  "extra_body": {
    "codex_capabilities": {
      "tool_schema_mode": "custom_only",
      "bypass_tool_call_reactor": true,
      "include_environment_context": false
    }
  }
}
```

**Note**: These settings are already the defaults, so you typically don't need to set them unless you want to override the enthusiast mode behavior.

## Troubleshooting

### Common Issues

- **Authentication failures (managed mode)**: verify you have at least one managed account (`manage_openai_codex_accounts.py list`) and that it is not in `needs_reauth` status.
- **Authentication failures (fallback mode)**: ensure your `auth.json` file exists at `%USERPROFILE%\.codex\auth.json` (Windows) or `~/.codex/auth.json` (Linux/macOS) and contains valid OAuth tokens.
- **Model not found**: Make sure you're using one of the supported model slugs (see Configuration section).
- **Rate limiting**: managed mode can rotate accounts after `429` responses; fallback mode cannot rotate and must wait for quota reset.
