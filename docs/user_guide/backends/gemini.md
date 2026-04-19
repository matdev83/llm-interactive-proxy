# Gemini Backends

The proxy provides multiple Gemini backend options to suit different authentication methods, billing preferences, and use cases. Choose the backend that best fits your environment and requirements.

## Gemini Front-end API

The proxy exposes a standard Google Gemini v1beta API interface, allowing you to use official Gemini SDKs and tools directly with the proxy. This interface translates requests to your configured backend (OpenAI, Anthropic, or Gemini).

### Supported Endpoints

- **Generate Content**: `POST /v1beta/models/{model}:generateContent`
- **Stream Generate Content**: `POST /v1beta/models/{model}:streamGenerateContent`
- **List Models**: `GET /v1beta/models`

### Usage Examples

**Generate Content:**

```bash
curl -X POST "http://localhost:8000/v1beta/models/gemini-pro:generateContent" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{
      "parts": [{"text": "Write a story about a magic backpack."}]
    }]
  }'
```

**Stream Generate Content:**

```bash
curl -X POST "http://localhost:8000/v1beta/models/gemini-pro:streamGenerateContent" \
  -H "Content-Type: application/json" \
  -d '{
    "contents": [{
      "parts": [{"text": "Write a story about a magic backpack."}]
    }]
  }'
```

This front-end interface allows you to swap the backend provider without changing your client code structure, as long as the client supports the Gemini API format.

## Overview

Google Gemini models are available through several backend configurations:

| Backend | Authentication | Cost | Best For |
|---------|----------------|------|----------|
| `gemini` | API key | Metered (pay-per-use) | Production apps, high-volume usage |
| `gemini-oauth-auto` | Self-managed OAuth | Free/Plan with rotation | Users with multiple accounts, high availability |
| `gemini-oauth-plan` | OAuth | Google One subscription | Users with active Google One subscription |
| `gemini-oauth-free` | OAuth | Free tier with limits | Users without Google One subscription |
| `gemini-cli-acp` | Gemini CLI ACP | Local OAuth token | Quality verifier agents, file-search sub-agents, web-search sub-agents with Google Search access |
| `gemini-cli-cloud-project` | OAuth + GCP Project | Billed to GCP project | Enterprise, team workflows, central billing |
| `antigravity-oauth` | Antigravity Token | Internal Debugging | **Internal Development Only** - Gemini Models |


## Gemini API Key Backend Feature Support

This section documents the feature parity status of the `gemini` (API key) backend connector with the official Google Gemini API specification.

### Endpoints

| Endpoint | Status | Description |
|----------|--------|-------------|
| generateContent | Supported | Non-streaming content generation |
| streamGenerateContent | Supported | Streaming content generation (SSE) |
| models.list | Supported | List available models |

### Generation Config Parameters

| Parameter | Status | Notes |
|-----------|--------|-------|
| `temperature` | Supported | Range 0.0-2.0 (clamped to 1.0 for older models) |
| `topP` | Supported | Nucleus sampling parameter |
| `topK` | Supported | Top-k sampling parameter |
| `maxOutputTokens` | Supported | Maximum tokens to generate |
| `stopSequences` | Supported | Stop sequences array |
| `candidateCount` | Supported | Maps from `n` parameter |
| `seed` | Passthrough | Passed to API, not officially documented |
| `presencePenalty` | Passthrough | Passed to API, not officially documented |
| `frequencyPenalty` | Passthrough | Passed to API, not officially documented |
| `responseMimeType` | Supported | For structured output (application/json) |
| `responseSchema` | Supported | JSON schema for structured output |
| `responseLogprobs` | Passthrough | Log probabilities |
| `logprobs` | Passthrough | Number of log probabilities |

### Thinking/Reasoning Config

| Parameter | Status | Description |
|-----------|--------|-------------|
| `thinkingConfig.thinkingBudget` | Supported | Token budget for reasoning |
| `thinkingConfig.reasoning_effort` | Supported | Effort level (low, medium, high) |
| `thinkingConfig.includeThoughts` | Supported | Include thoughts in response |

### Content Features

| Feature | Status | Description |
|---------|--------|-------------|
| Text content | Supported | Plain text messages |
| Multi-turn conversations | Supported | User/model role alternation |
| System instructions | Supported | Via contents or systemInstruction field |
| Inline images (base64) | Supported | `inlineData` with base64 encoded images |
| File references | Supported | `fileData` with file URIs |
| Function calling | Supported | `tools` with `function_declarations` |
| Function responses | Supported | `functionResponse` parts |
| Tool configuration | Supported | `toolConfig` with `functionCallingConfig` |

### Safety and Caching

| Feature | Status | Notes |
|---------|--------|-------|
| `safetySettings` | Supported | Via `extra_body.gemini_safety_settings` |
| `cachedContent` | Supported | Via `extra_body.gemini_cached_content` |

### Response Features

| Feature | Status | Description |
|---------|--------|-------------|
| `candidates` array | Supported | Response candidates |
| `content.parts` | Supported | Text and function call parts |
| `finishReason` | Supported | STOP, MAX_TOKENS, SAFETY, RECITATION |
| `safetyRatings` | Supported | Safety rating per category |
| `usageMetadata` | Supported | Token usage information |
| Streaming (SSE) | Supported | Server-Sent Events format |

### Parameter Translation (From Other Frontends)

When requests come from OpenAI or Anthropic frontends, parameters are automatically translated:

| Source Parameter | Gemini Parameter |
|------------------|------------------|
| `temperature` | `temperature` |
| `top_p` | `topP` |
| `max_tokens` / `max_completion_tokens` | `maxOutputTokens` |
| `stop` | `stopSequences` |
| `n` | `candidateCount` |
| `seed` | `seed` |
| `presence_penalty` | `presencePenalty` |
| `frequency_penalty` | `frequencyPenalty` |
| `response_format` (json_schema) | `responseMimeType` + `responseSchema` |

### Unsupported Parameters

These parameters are logged as warnings and ignored:

| Parameter | Reason |
|-----------|--------|
| `logit_bias` | Not supported by Gemini API |
| `user` | Not supported by Gemini API |

---

## Gemini API Key Backend

The standard Gemini backend uses an API key for authentication and bills on a pay-per-use basis.

### Configuration

```bash
export GEMINI_API_KEY="AIza..."
python -m src.core.cli --default-backend gemini
```

### YAML Configuration

```yaml
# config.yaml
backends:
  gemini:
    type: gemini

default_backend: gemini
```

### Usage Example

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "gemini-2.5-pro",
    "messages": [
      {"role": "user", "content": "Hello, Gemini!"}
    ]
  }'
```

### Use Cases

- Production applications with predictable billing
- High-volume API usage
- Applications requiring guaranteed availability
- Enterprise deployments

## Gemini OAuth Plan Backend

For users with an active Google One (or future equivalent) subscription, this backend uses personal OAuth authentication.

### Configuration

**Debugging Override Flag Required:**

To use this backend, you **must** launch the proxy with the following CLI flag:

```bash
--enable-gemini-oauth-plan-backend-debugging-override
```

Without this flag, the backend is disabled and will reject all requests with a 403 Forbidden error.

```bash
# Install and authenticate with Google Gemini CLI (one-time)
gemini auth

# Start the proxy
python -m src.core.cli --default-backend gemini-oauth-plan --enable-gemini-oauth-plan-backend-debugging-override
```

### Disclaimer: Internal Development Use Only

**IMPORTANT: PLEASE READ BEFORE USING THIS BACKEND**

This backend connector is implemented **solely** for the internal development purposes of this project. Its primary function is to enable the proper discovery, analysis, and implementation of secure, protocol-specific behaviors required for interoperability and compatibility layers.

**This connector is NOT intended for general usage, production deployment, or as a means to bypass intended access restrictions.**

By using this proxy with the Gemini OAuth Plan backend configuration, you acknowledge and agree to the following terms, which constitute a binding arrangement between you and the authors of this project:

1. **Non-Affiliation**: This project is an independent open-source initiative. It is **not affiliated with, endorsed by, authorized by, or in any way officially connected to** Google or any of their subsidiaries or affiliates. All product and company names are trademarks™ or registered® trademarks of their respective holders. Use of them does not imply any affiliation with or endorsement by them.
2. **Restricted Access**: The use of the `--enable-gemini-oauth-plan-backend-debugging-override` CLI flag is strictly reserved for the project's **developers, contributors, and maintainers**. Its sole purpose is debugging and maintaining the proxy's compatibility features.
3. **Prohibited Use**: You must **not** use the debugging override flag if you do not belong to the authorized groups mentioned above.
4. **No Liability**: The authors, contributors, and maintainers of this project hold **no responsibility or liability** for any consequences arising from the use of this flag or backend in violation of these rules, or for any violations of third-party Terms of Service resulting from such use.
5. **User Responsibility**: You accept full responsibility for ensuring your use of this tool complies with all applicable laws and third-party agreements.
6. **Compliance with Provider Terms**: Users of any backend connectors implemented in this proxy server are strictly required to respect all related Terms of Service (ToS) and other agreements with the respective backend providers. You are solely responsible for verifying that your use of this software is compatible with those agreements.
7. **Indemnification**: You agree to indemnify, defend, and hold harmless the authors and contributors of this project from and against any and all claims, liabilities, damages, losses, or expenses, including legal fees and costs, arising out of or in any way connected with your access to or use of this backend or the debugging override flag.

**If you do not agree to these terms, do not use the Gemini OAuth Plan backend or the debugging override flag.**

### Features

- No API key required
- Uses your Google One subscription
- Automatic token refresh
- Personal account access

### Token Management

The proxy automatically:

- Validates OAuth tokens on startup
- Watches `oauth_creds.json` for changes
- Triggers Gemini CLI in the background when tokens are close to expiring
- No manual restarts required

## Gemini OAuth Free Backend

For users without a Google One subscription, this backend provides access to Google's free tier.

### Configuration

**Debugging Override Flag Required:**

To use this backend, you **must** launch the proxy with the following CLI flag:

```bash
--enable-gemini-oauth-free-backend-debugging-override
```

Without this flag, the backend is disabled and will reject all requests with a 403 Forbidden error.

```bash
# Install and authenticate with Google Gemini CLI (one-time)
gemini auth

# Start the proxy
python -m src.core.cli --default-backend gemini-oauth-free --enable-gemini-oauth-free-backend-debugging-override
```

### Disclaimer: Internal Development Use Only

**IMPORTANT: PLEASE READ BEFORE USING THIS BACKEND**

This backend connector is implemented **solely** for the internal development purposes of this project. Its primary function is to enable the proper discovery, analysis, and implementation of secure, protocol-specific behaviors required for interoperability and compatibility layers.

**This connector is NOT intended for general usage, production deployment, or as a means to bypass intended access restrictions.**

By using this proxy with the Gemini OAuth Free backend configuration, you acknowledge and agree to the following terms, which constitute a binding arrangement between you and the authors of this project:

1. **Non-Affiliation**: This project is an independent open-source initiative. It is **not affiliated with, endorsed by, authorized by, or in any way officially connected to** Google or any of their subsidiaries or affiliates. All product and company names are trademarks™ or registered® trademarks of their respective holders. Use of them does not imply any affiliation with or endorsement by them.
2. **Restricted Access**: The use of the `--enable-gemini-oauth-free-backend-debugging-override` CLI flag is strictly reserved for the project's **developers, contributors, and maintainers**. Its sole purpose is debugging and maintaining the proxy's compatibility features.
3. **Prohibited Use**: You must **not** use the debugging override flag if you do not belong to the authorized groups mentioned above.
4. **No Liability**: The authors, contributors, and maintainers of this project hold **no responsibility or liability** for any consequences arising from the use of this flag or backend in violation of these rules, or for any violations of third-party Terms of Service resulting from such use.
5. **User Responsibility**: You accept full responsibility for ensuring your use of this tool complies with all applicable laws and third-party agreements.
6. **Compliance with Provider Terms**: Users of any backend connectors implemented in this proxy server are strictly required to respect all related Terms of Service (ToS) and other agreements with the respective backend providers. You are solely responsible for verifying that your use of this software is compatible with those agreements.
7. **Indemnification**: You agree to indemnify, defend, and hold harmless the authors and contributors of this project from and against any and all claims, liabilities, damages, losses, or expenses, including legal fees and costs, arising out of or in any way connected with your access to or use of this backend or the debugging override flag.

**If you do not agree to these terms, do not use the Gemini OAuth Free backend or the debugging override flag.**

### Features

- No API key required
- Free tier access
- Personal account authentication
- Automatic token refresh

### Limitations

- Subject to free tier rate limits
- May have lower priority during high demand
- Not recommended for production applications

## Gemini CLI Cloud Project Backend

For enterprise and team workflows, this backend bills to your Google Cloud Platform project.

### Configuration

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"

# Provide Application Default Credentials via one of:

# Option A: User credentials (interactive)
gcloud auth application-default login

# Option B: Service account file
export GOOGLE_APPLICATION_CREDENTIALS="/absolute/path/to/service-account.json"

# Start the proxy
python -m src.core.cli --default-backend gemini-cli-cloud-project
```

### YAML Configuration

```yaml
# config.yaml
backends:
  gemini-cli-cloud-project:
    type: gemini-cli-cloud-project
    project_id: "your-project-id"

default_backend: gemini-cli-cloud-project
```

### Use Cases

- Enterprise deployments
- Team workflows with central billing
- Corporate accounts
- Applications requiring GCP integration

### Requirements

- `GOOGLE_CLOUD_PROJECT` environment variable
- Application Default Credentials (ADC) or service account file
- GCP project with Gemini API enabled

## Gemini CLI ACP Backend

This backend connects to the local `gemini` CLI through the Agent Control Protocol (ACP). It launches Gemini CLI inside the detected project directory when available, so Gemini's built-in workspace tools operate against the same repository the client is working on.

### Recommended Use Cases

- Quality verifier agents that need an independent second opinion with workspace visibility
- File-search sub-agents that can benefit from Gemini CLI's built-in repository inspection tools
- Web-search sub-agents that benefit from Gemini CLI access to Google Search services

### Not Recommended As Main Session Backend

This backend is usually not the best fit for the primary general-purpose coding agent handling the entire session flow. The ACP tool model is optimized around Gemini CLI's native tools and interaction style, so mapping every proxy-side tool and session behavior into that environment is more complex and less predictable than with backends designed around the proxy's normal request/response flow.

### Configuration

```bash
# Authenticate once with Gemini CLI
gemini auth

# Start the proxy with Gemini ACP as default backend
python -m src.core.cli --default-backend gemini-cli-acp
```

The connector resolves the Gemini CLI executable across platforms, including
Windows `gemini.cmd` / `gemini.exe` shims. If your installation is not on PATH,
set `backends.<instance>.extra.gemini_cli_executable` to the full executable
path.

#### Idle subprocess cleanup (ACP)

After each completed chat turn, the proxy may terminate the pooled Gemini CLI ACP process after it stays idle for `stale_acp_agent_kill_idle_seconds` (default 3600); new traffic cancels the pending shutdown. This matches the shared ACP behavior described under [Agent Client Protocol (ACP) backends in the overview](overview.md#agent-client-protocol-acp-backends). Disable via `--disable-stale-acp-agent-kills`, `DISABLE_STALE_ACP_AGENT_KILLS=true`, or `disable_stale_acp_agent_kills: true`. Override the delay with `--stale-acp-agent-kill-idle-seconds`, `STALE_ACP_AGENT_KILL_IDLE_SECONDS`, or `stale_acp_agent_kill_idle_seconds` in the config file (CLI overrides env overrides file).

### Usage

Use canonical model names through the proxy, for example:

```text
gemini-cli-acp:google/gemini-3-flash-preview
```

The proxy keeps the canonical `google/` prefix in routed model names, and the connector strips it before sending the model to Gemini CLI when the CLI expects the unprefixed form.

## Antigravity OAuth Backend (Internal Use Only)

This specialized backend integrates with the Antigravity app's authentication and sandbox endpoint infrastructure for internal development and compatibility testing.

See dedicated documentation:

- **[Antigravity OAuth Backend](antigravity-oauth.md)** - For internal debugging with Gemini and Claude models

## Gemini OAuth Auto Backend

The multi-account Gemini connector with automatic token refresh and round-robin rotation. This backend manages its own OAuth lifecycle without requiring external CLI tools.

See dedicated documentation:

- **[Gemini OAuth Auto Backend](gemini-oauth-auto.md)** - For multi-account setup and automatic rotation

### Features

- **Multi-account Support**: Register multiple Google accounts and rotate between them.
- **Self-contained OAuth**: Handles the authorization flow directly via a local callback server.
- **Automatic Rotation**: Automatically switches to the next available account if one reaches its quota.
- **Proactive Refresh**: Refreshes access tokens in the background before they expire.

### Configuration

To add accounts, use the provided management script:

```bash
./.venv/Scripts/python.exe scripts/manage_gemini_accounts.py add
```

Skip onboarding/project ID validation (advanced use only):
```bash
./.venv/Scripts/python.exe scripts/manage_gemini_accounts.py add --skip-validation
```

Follow the interactive instructions to authorize each account.

### YAML Configuration

```yaml
backends:
  gemini-oauth-auto:
    type: gemini-oauth-auto
    extra:
      selection_strategy: "session-affinity"  # or "random", "first-available", "round-robin"
      session_affinity_ttl_seconds: 86400
      session_affinity_max_entries: 10000
      refresh_buffer_seconds: 300
```

### Management Script Usage

The `scripts/manage_gemini_accounts.py` script provides several commands:

- `list`: Show all registered accounts and their status.
- `add`: Register a new Google account (validates Code Assist onboarding/project ID).
- `add --skip-validation`: Skip onboarding/project ID validation (advanced use only).
- `update <account-id>`: Re-authorize an existing account.
- `remove <account-id>`: Remove an account from local storage.
- `set-project-id <account-id> --project-id <PROJECT_ID>`: Set/validate Cloud Project ID.

## Common Configuration


### Model Parameters

All Gemini backends support URI model parameters:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemini:gemini-2.5-pro?temperature=0.7",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### Fallback Configuration

Disable automatic fallback to `gemini-2.5-flash` when rate-limited:

```bash
export DISABLE_GEMINI_OAUTH_FALLBACK=true
```

Or in config:

```yaml
backends:
  gemini-oauth-plan:
    disable_fallback: true
```

## Troubleshooting

### OAuth Token Issues

If you encounter authentication errors:

```bash
# Re-authenticate with Gemini CLI
gemini auth

# Verify token file exists
ls ~/.config/gemini-cli/oauth_creds.json
```

### Rate Limiting

- Free tier backends have lower rate limits
- Consider upgrading to API key or GCP-billed backend
- Enable failover to switch to alternative models

### Model Not Found

- Verify the model name is correct (e.g., `gemini-2.5-pro`, `gemini-1.5-flash`)
- Check that your authentication method has access to the requested model
- Some models may require special access

### GCP Project Issues

For `gemini-cli-cloud-project`:

- Verify `GOOGLE_CLOUD_PROJECT` is set correctly
- Ensure the project has Gemini API enabled
- Check that ADC or service account credentials are valid

## Choosing the Right Backend

### Use `gemini` (API Key) if

- You need production-grade reliability
- You have high-volume usage
- You want predictable billing
- You need guaranteed availability

### Use `gemini-oauth-plan` if

- You have a Google One subscription
- You want to use your personal account
- You prefer subscription-based billing
- You need moderate usage

### Use `gemini-oauth-free` if

- You don't have a Google One subscription
- You want to try Gemini for free
- You have low-volume usage
- You're prototyping or testing

### Use `gemini-cli-cloud-project` if

- You're in an enterprise environment
- You need central billing to GCP
- You want team-wide access
- You need GCP integration

## Related Features

- [Model Name Rewrites](../features/model-name-rewrites.md) - Route Gemini models dynamically
- [Hybrid Backend](../features/hybrid-backend.md) - Combine Gemini with other models
- [Planning Phase Overrides](../features/planning-phase.md) - Use Gemini for planning phases

## Related Documentation

- [Backend Overview](overview.md)
- [OpenAI Backend](openai.md)
- [Anthropic Backend](anthropic.md)
