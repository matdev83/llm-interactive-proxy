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


## Supported Models

The backend dynamically fetches the list of available models from the OpenCode Zen gateway. The proxy normalizes these names into a standard `vendor/model-name` format. To use a model via this backend, you must prefix it with `opencode-zen:`.

As of the last check, supported models include:

- `opencode-zen:anthropic/claude-opus-4-5`
- `opencode-zen:anthropic/claude-sonnet-4-5`
- `opencode-zen:anthropic/claude-3-5-haiku`
- `opencode-zen:google/gemini-3-pro`
- `opencode-zen:openai/gpt-5.1`
- `opencode-zen:openai/gpt-5.1-codex`
- `opencode-zen:qwen/qwen3-coder`
- `opencode-zen:z-ai/glm-4.6`
- `opencode-zen:moonshotai/kimi-k2-0905`
- `opencode-zen:x-ai/grok-code-fast-1`
- `opencode-zen:stealth/big-pickle`
...and several others.

## Usage Example

Once the proxy is running with the override flag, you can send requests as follows:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "opencode-zen:x-ai/grok-code-fast-1",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```