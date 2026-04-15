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
