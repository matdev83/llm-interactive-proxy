# OpenCode Zen Backend

The `opencode-zen` backend allows the LLM Interactive Proxy to route requests through OpenCode's Zen gateway using the credentials managed by the OpenCode CLI. This integration provides seamless access to premium models like `anthropic/claude-sonnet-4` and `openai/gpt-4.1` for users who are already authenticated with the OpenCode CLI.

## Prerequisites

1. **OpenCode CLI Installed**: You must have the `opencode` CLI tool installed on your system.
2. **Authenticated**: You must be logged in via the CLI.
   ```bash
   opencode auth login
   ```
   This command generates the `auth.json` file that this backend reads.

## Configuration

To use this backend, add it to your configuration (e.g., `config/config.yaml`) or rely on the default auto-discovery if enabled.

### Basic Configuration

```yaml
backends:
  opencode-zen:
    enabled: true
    # Optional: Custom API URL
    # api_base_url: "https://opencode.ai/zen/v1"
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENCODE_AUTH_PATH` | Custom path to the `auth.json` file. | OS-specific default (see below) |
| `OPENCODE_ZEN_API_URL` | Override the gateway API endpoint. | `https://opencode.ai/zen/v1` |

## Credential Locations

The backend automatically detects the `auth.json` file created by the OpenCode CLI in standard locations:

| Platform | Default Path |
|----------|--------------|
| **Windows** | `%LOCALAPPDATA%\opencode\auth.json` |
| **Linux** | `$XDG_DATA_HOME/opencode/auth.json` or `~/.local/share/opencode/auth.json` |
| **macOS** | `$XDG_DATA_HOME/opencode/auth.json` or `~/.local/share/opencode/auth.json` |

If your credentials are stored elsewhere, use the `OPENCODE_AUTH_PATH` environment variable or `credentials_path` in config.

## Supported Models

The backend dynamically fetches the list of available models from the OpenCode Zen gateway. As of the latest check, the following models are supported:

### Anthropic
- `anthropic/claude-opus-4-5`
- `anthropic/claude-opus-4-1`
- `anthropic/claude-sonnet-4-5`
- `anthropic/claude-sonnet-4`
- `anthropic/claude-3-5-haiku`
- `anthropic/claude-haiku-4-5`

### OpenAI
- `openai/gpt-5.1`
- `openai/gpt-5`
- `openai/gpt-5.1-codex-max`
- `openai/gpt-5.1-codex`
- `openai/gpt-5-codex`
- `openai/gpt-5-nano`

### Google
- `google/gemini-3-pro`

### Other Vendors
- `qwen/qwen3-coder`
- `zhipuai/glm-4.6`
- `moonshot/kimi-k2`
- `moonshot/kimi-k2-thinking`
- `xai/grok-code`
- `deepmind/alpha-gd4`
- `misc/big-pickle`

When sending requests, you can use either the plain model name (e.g., `claude-sonnet-4`) or prefix it with the vendor (e.g., `opencode-zen:claude-sonnet-4`) to ensure routing to this specific backend. Note that the backend normalized the model names, so `anthropic/claude-sonnet-4` is accessed via `opencode-zen:claude-sonnet-4`.

## Usage Example

Once configured, you can send requests using the proxy:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "opencode-zen:anthropic/claude-sonnet-4",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Troubleshooting

### "OpenCode credentials not found"
- Ensure you have run `opencode auth login`.
- Verify the file exists at the expected path for your OS.
- If using a custom path, check `OPENCODE_AUTH_PATH`.

### "OpenCode OAuth token is expired"
- The backend automatically reloads the credentials file if the token is expired.
- If the error persists, the refresh token might also be invalid. Run `opencode auth login` again to refresh your session.

### "Backend is not functional"
- Check the application logs for specific initialization errors.
- Ensure the `auth.json` file is valid JSON and contains the `opencode` provider key with OAuth credentials.
