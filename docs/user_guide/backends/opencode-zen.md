# OpenCode Zen Backend

The `opencode-zen` backend allows the LLM Interactive Proxy to route requests through OpenCode's Zen gateway. It authenticates by reading the credentials managed by the `opencode` CLI.

## Disclaimer: Internal Development Use Only

**IMPORTANT: PLEASE READ BEFORE USING THIS BACKEND**

This backend connector is implemented **solely** for internal development, research, and compatibility testing purposes. Its primary function is to enable the discovery and implementation of protocol-specific behaviors.

**This connector is NOT intended for general public usage or production deployment.**

By using this proxy with the OpenCode Zen backend configuration, you acknowledge and agree to the following terms:

1.  **Non-Affiliation**: This project is an independent open-source initiative and is not affiliated with, endorsed by, or officially connected to the creators of OpenCode, Anthropic, Google, OpenAI, xAI, or any other model provider.
2.  **Restricted Access**: The use of the `--enable-opencode-zen-backend-debugging-override` CLI flag is strictly reserved for the project's **developers, contributors, and maintainers**. Its sole purpose is debugging and maintaining the proxy's features.
3.  **Prohibited Use**: You must **not** use the debugging override flag if you do not belong to the authorized groups mentioned above.
4.  **No Liability**: The authors and contributors of this project hold no responsibility for any consequences arising from the use of this flag or for any violations of third-party Terms of Service.
5.  **User Responsibility**: You accept full responsibility for ensuring your use of this tool complies with all applicable laws and the terms of service of any third-party model providers accessed through the gateway.

**If you do not agree to these terms, do not use the OpenCode Zen backend or the debugging override flag.**

## Backend Guard

By default, this backend is **disabled**. To enable it, you must start the application with the following CLI flag:

```bash
--enable-opencode-zen-backend-debugging-override
```

Attempting to use the backend without this flag will result in a `403 Forbidden` error.

## Prerequisites

1.  **OpenCode CLI Installed**: You must have the `opencode` CLI tool installed on your system.
2.  **Authenticated**: You must be logged in via `opencode auth login`. This command generates the `auth.json` file that this backend reads.

## Configuration

The backend automatically discovers credentials from standard locations, so minimal configuration is needed.

**YAML (`config.yaml`):**
```yaml
backends:
  opencode-zen:
    # No specific configuration is required if using default paths.
    # The backend is enabled via the CLI flag.
```

### Environment Variables
- `OPENCODE_AUTH_PATH`: Use this to provide a custom path to your `auth.json` file.

### Credential Locations
The connector automatically finds the `auth.json` file in these default locations:

| Platform  | Default Path                               |
|-----------|--------------------------------------------|
| Windows   | `%LOCALAPPDATA%\opencode\auth.json`          |
| Linux     | `~/.local/share/opencode/auth.json`        |
| macOS     | `~/Library/Application Support/opencode/auth.json` |


### OAuth tokens and refresh (important)

The optional `llm-proxy-oauth-connectors` package implements this backend. For `type: "oauth"` entries, OpenCode’s `auth.json` uses the fields **`access`**, **`refresh`**, and **`expires`** under the `opencode` key (not `refresh_token`).

**There is no proxy `config.yaml` switch that performs an OAuth refresh HTTP call for Zen.** Today the connector:

- Loads and caches credentials from `auth.json`.
- Before each chat completion, if the access token looks **expired**, it **reloads the file from disk** (so another process—usually the **OpenCode CLI**—must have written a new token).
- On **401**, it reloads `auth.json` once and retries.

So “triggering refresh” in practice means **refreshing tokens where OpenCode already does**—typically by running or keeping the **`opencode` CLI** so it updates `auth.json` (for example `opencode auth login` again if `refresh` is missing or tokens are invalid). Check the current CLI with `opencode auth --help` for your installed version.

If the proxy logs `Health check failed - no refresh token in credentials`, the `opencode` object in `auth.json` is missing the **`refresh`** field (wrong auth type, incomplete login, or stale file). Fix that with a full Zen OAuth login via the CLI, not a proxy-only setting.

Optional YAML still passes through to connector `initialize()`, for example:

```yaml
backends:
  opencode-zen:
    credentials_path: "C:/path/to/auth.json"   # or rely on OPENCODE_AUTH_PATH
    extra:
      enable_opencode_zen_backend_debugging_override: true   # only if not using the CLI flag
```

Automatic refresh by **calling a Zen/OpenCode token endpoint** (and writing `auth.json` back) would need to be implemented in **`llm-proxy-oauth-connectors`**, along the same lines as `qwen_oauth`’s token POST + save.

## Supported Models

On startup, the connector loads model IDs from the live Zen OpenAI-compatible endpoint `GET https://opencode.ai/zen/v1/models` (or `{api_base_url}/models` if you override the base URL). It tries that request with your OpenCode credentials first, then repeats without credentials if the catalog is still empty or the authenticated call fails (the catalog is publicly reachable in practice). Only if both remote attempts fail does it use an embedded snapshot list. Each `id` is normalized to a `vendor/model-name` form where the connector can infer a vendor; otherwise the raw gateway id is kept. In requests to this proxy, prefix the normalized (or raw) id with `opencode-zen:`.

The connector keeps the resolved catalog in memory and **refetches `/models` at most about every 10 minutes** when callers use the async model enumeration path (for example capability discovery); synchronous `get_available_models()` returns the latest cached list without doing I/O.

The public `/models` response can change at any time; the list below is a **documentation snapshot** only (probed **2026-03-21**). Prefer calling `/v1/models` on a running proxy or the gateway directly for the live catalog. To regenerate the JSON snapshot in this repository, run:

```bash
./.venv/Scripts/python.exe dev/scripts/probe_opencode_zen_models.py
```

Snapshot (selector after `opencode-zen:`):

- `opencode-zen:anthropic/claude-opus-4-6`
- `opencode-zen:anthropic/claude-opus-4-5`
- `opencode-zen:anthropic/claude-opus-4-1`
- `opencode-zen:anthropic/claude-sonnet-4-6`
- `opencode-zen:anthropic/claude-sonnet-4-5`
- `opencode-zen:anthropic/claude-sonnet-4`
- `opencode-zen:anthropic/claude-3-5-haiku`
- `opencode-zen:anthropic/claude-haiku-4-5`
- `opencode-zen:google/gemini-3.1-pro`
- `opencode-zen:google/gemini-3-pro`
- `opencode-zen:google/gemini-3-flash`
- `opencode-zen:openai/gpt-5.4`
- `opencode-zen:openai/gpt-5.4-pro`
- `opencode-zen:openai/gpt-5.4-mini`
- `opencode-zen:openai/gpt-5.4-nano`
- `opencode-zen:openai/gpt-5.3-codex-spark`
- `opencode-zen:openai/gpt-5.3-codex`
- `opencode-zen:openai/gpt-5.2`
- `opencode-zen:openai/gpt-5.2-codex`
- `opencode-zen:openai/gpt-5.1`
- `opencode-zen:openai/gpt-5.1-codex-max`
- `opencode-zen:openai/gpt-5.1-codex`
- `opencode-zen:openai/gpt-5.1-codex-mini`
- `opencode-zen:openai/gpt-5`
- `opencode-zen:openai/gpt-5-codex`
- `opencode-zen:openai/gpt-5-nano`
- `opencode-zen:z-ai/glm-5`
- `opencode-zen:z-ai/glm-4.7`
- `opencode-zen:z-ai/glm-4.6`
- `opencode-zen:minimax/minimax-m2.5`
- `opencode-zen:minimax/minimax-m2.5-free`
- `opencode-zen:minimax/minimax-m2.1`
- `opencode-zen:mimo-v2-pro-free`
- `opencode-zen:mimo-v2-omni-free`
- `opencode-zen:mimo-v2-flash-free`
- `opencode-zen:moonshotai/kimi-k2.5`
- `opencode-zen:moonshotai/kimi-k2-0905`
- `opencode-zen:moonshotai/kimi-k2-thinking`
- `opencode-zen:trinity-large-preview-free`
- `opencode-zen:stealth/big-pickle`
- `opencode-zen:nemotron-3-super-free`

If **both** live `/models` attempts fail during initialization, the optional `llm-proxy-oauth-connectors` package uses a **hardcoded** snapshot of gateway ids (maintained to mirror `/models`); that list can lag the live gateway.

## Usage Example

Once the proxy is running with the override flag, you can send requests as follows:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "opencode-zen:openai/gpt-5.2",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```