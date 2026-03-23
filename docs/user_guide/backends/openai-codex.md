# OpenAI Codex Backend

The OpenAI Codex backend connector is a specialized integration designed to route requests through the OpenAI Codex / Responses API infrastructure using OAuth tokens. It mimics the authentication and request patterns of the Codex CLI to facilitate development and compatibility testing.

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
- `OPENAI_CODEX_PATH`: Path to the Codex configuration directory containing `auth.json` (optional).
- `OPENAI_API_BASE_URL`: Override for the API base URL.

### Authentication

The connector attempts to automatically locate Codex authentication tokens from standard locations:
- Windows: `%USERPROFILE%\.codex\auth.json`
- Cross-platform: `~/.codex/auth.json`

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

- **Authentication failures**: Ensure your `auth.json` file exists at `%USERPROFILE%\.codex\auth.json` (Windows) or `~/.codex/auth.json` (Linux/macOS) and contains valid OAuth tokens from your ChatGPT account.
- **Model not found**: Make sure you're using one of the supported model slugs (see Configuration section).
- **Rate limiting**: The Codex backend uses your ChatGPT plan quota, which may have different limits than the API key.
