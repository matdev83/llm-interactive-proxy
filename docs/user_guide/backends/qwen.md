# Qwen Backend

The Qwen backend provides access to Alibaba's Qwen (Tongyi Qianwen) models through OAuth authentication. Qwen models are known for their strong performance, especially in Chinese language tasks and coding.

## Overview

Qwen (通义千问) is Alibaba's large language model series. The proxy supports the `qwen-oauth` backend, which uses OAuth authentication through the Qwen CLI for access to Qwen models.

## Key Features

- OpenAI-compatible API
- OAuth authentication (no API key required)
- Strong Chinese language support
- Excellent coding capabilities (Qwen3-Coder models)
- Competitive performance
- Free tier available

## Configuration

### Prerequisites

The Qwen backend requires the Qwen CLI to be installed and authenticated:

```bash
# Install Qwen CLI (if not already installed)
# Follow Qwen's official installation instructions

# Authenticate with Qwen CLI (one-time)
# This creates oauth_creds.json in your config directory
qwen auth
```

### Debugging Override Flag Required

To use this backend, you **must** launch the proxy with the following CLI flag:

```bash
--enable-qwen-oauth-backend-debugging-override
```

Without this flag, the backend is disabled and will reject all requests with a 403 Forbidden error.

```bash
# Start the proxy
python -m src.core.cli --default-backend qwen-oauth --enable-qwen-oauth-backend-debugging-override
```

### Disclaimer: Internal Development Use Only

**IMPORTANT: PLEASE READ BEFORE USING THIS BACKEND**

This backend connector is implemented **solely** for the internal development purposes of this project. Its primary function is to enable the proper discovery, analysis, and implementation of secure, protocol-specific behaviors required for interoperability and compatibility layers.

**This connector is NOT intended for general usage, production deployment, or as a means to bypass intended access restrictions.**

By using this proxy with the Qwen OAuth backend configuration, you acknowledge and agree to the following terms, which constitute a binding arrangement between you and the authors of this project:

1.  **Non-Affiliation**: This project is an independent open-source initiative. It is **not affiliated with, endorsed by, authorized by, or in any way officially connected to** Alibaba Cloud, the Qwen team, or any of their subsidiaries or affiliates. All product and company names are trademarks™ or registered® trademarks of their respective holders. Use of them does not imply any affiliation with or endorsement by them.
2.  **Restricted Access**: The use of the `--enable-qwen-oauth-backend-debugging-override` CLI flag is strictly reserved for the project's **developers, contributors, and maintainers**. Its sole purpose is debugging and maintaining the proxy's compatibility features.
3.  **Prohibited Use**: You must **not** use the debugging override flag if you do not belong to the authorized groups mentioned above.
4.  **No Liability**: The authors, contributors, and maintainers of this project hold **no responsibility or liability** for any consequences arising from the use of this flag or backend in violation of these rules, or for any violations of third-party Terms of Service resulting from such use.
5.  **User Responsibility**: You accept full responsibility for ensuring your use of this tool complies with all applicable laws and third-party agreements.
6.  **Compliance with Provider Terms**: Users of any backend connectors implemented in this proxy server are strictly required to respect all related Terms of Service (ToS) and other agreements with the respective backend providers. You are solely responsible for verifying that your use of this software is compatible with those agreements.
7.  **Indemnification**: You agree to indemnify, defend, and hold harmless the authors and contributors of this project from and against any and all claims, liabilities, damages, losses, or expenses, including legal fees and costs, arising out of or in any way connected with your access to or use of this backend or the debugging override flag.

**If you do not agree to these terms, do not use the Qwen OAuth backend or the debugging override flag.**

### Environment Variables

No API key is required. The backend reads OAuth credentials from the local `oauth_creds.json` file created by the Qwen CLI.

### CLI Arguments

```bash
# Start proxy with Qwen as default backend
python -m src.core.cli --default-backend qwen-oauth

# With specific model
python -m src.core.cli --default-backend qwen-oauth --force-model qwen3-coder-plus
```

### YAML Configuration

In this repository, `qwen-oauth` is typically configured in the backend-instances file
`config/backends/backend-instances/qwen-oauth.default.yaml` (under `extra`).

```yaml
# config.yaml
backends:
  qwen-oauth:
    type: qwen-oauth
    extra:
      enable_qwen_oauth_backend_debugging_override: true
      enable_qwen_oauth_initial_rate_limit_retry: true
      qwen_oauth_initial_rate_limit_retry_max_wait_seconds: 10.0
      qwen_oauth_initial_rate_limit_retry_random_min_seconds: 3.0
      qwen_oauth_initial_rate_limit_retry_random_max_seconds: 10.0

default_backend: qwen-oauth
```

The Qwen OAuth connector will hold the first recoverable upstream rate-limit response for up to 10 seconds, retry once, and only surface the error if the second attempt also fails. If the upstream sends `Retry-After`, that value is used and capped to your configured max wait; otherwise the connector waits for a random fallback delay before retrying.

Rate-limit retry behavior is fully configurable via backend `extra` parameters:

- `enable_qwen_oauth_initial_rate_limit_retry` (`bool`, default `true`): enable/disable initial retry behavior.
- `qwen_oauth_initial_rate_limit_retry_max_wait_seconds` (`float`, default `10.0`): upper bound for any retry wait.
- `qwen_oauth_initial_rate_limit_retry_random_min_seconds` (`float`, default `3.0`): minimum random fallback wait.
- `qwen_oauth_initial_rate_limit_retry_random_max_seconds` (`float`, default `10.0`): maximum random fallback wait.

At runtime (DEBUG logs), the connector now also reports connector-wide backoff state using messages like:

- `Qwen OAuth connector-wide rate-limit backoff recorded: wait=...`
- `Qwen OAuth connector-wide rate-limit backoff active: remaining=...`

## Available Models

Qwen offers several model variants:

- **Qwen3-Coder**: Specialized for coding tasks
- **Qwen3-Coder-Plus**: Enhanced coding model with better performance
- **Qwen-Turbo**: Fast general-purpose model
- **Qwen-Plus**: Enhanced general-purpose model
- **Qwen-Max**: Most capable general-purpose model

## Usage Examples

### Basic Chat Completion

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "qwen3-coder-plus",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

### Coding Task

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "qwen3-coder-plus",
    "messages": [
      {"role": "user", "content": "Write a Python function to implement binary search"}
    ]
  }'
```

### Streaming Response

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "qwen3-coder-plus",
    "messages": [
      {"role": "user", "content": "Explain recursion with examples"}
    ],
    "stream": true
  }'
```

### Chinese Language Task

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "qwen-plus",
    "messages": [
      {"role": "user", "content": "请解释一下Python的装饰器"}
    ]
  }'
```

## Use Cases

### Coding Workflows

Qwen3-Coder models excel at:

- Code generation in multiple languages
- Code completion and suggestions
- Code review and refactoring
- Debugging assistance
- Technical documentation

### Chinese Language Applications

Qwen models are excellent for:

- Chinese language understanding and generation
- Chinese-English translation
- Chinese text analysis
- Chinese content creation

### Cost-Effective Development

Use Qwen for:

- Free tier development and testing
- Cost-effective alternative to Western providers
- High-quality coding assistance
- Bilingual applications

## OAuth Token Management

The proxy automatically manages OAuth tokens:

- Reads credentials from `oauth_creds.json`
- Handles token refresh automatically
- No manual token management required

If you encounter authentication issues, re-authenticate with the Qwen CLI:

```bash
qwen auth
```

## Model Parameters

You can specify model parameters using URI syntax:

```bash
# With temperature
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-oauth:qwen3-coder-plus?temperature=0.7",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

See [URI Model Parameters](../features/uri-model-parameters.md) for more details.

## Troubleshooting

### 401 Unauthorized

- Verify you've authenticated with Qwen CLI: `qwen auth`
- Check that `oauth_creds.json` exists in the expected location
- Try re-authenticating if the token has expired

### OAuth Token Expired

```bash
# Re-authenticate with Qwen CLI
qwen auth

# Restart the proxy
python -m src.core.cli --default-backend qwen-oauth
```

### Model Not Found

- Verify the model name is correct (e.g., `qwen3-coder-plus`)
- Check that your account has access to the requested model
- Some models may require special access or higher account tiers

### Rate Limiting

- Free tier accounts have rate limits
- Consider upgrading for higher limits
- Use failover to switch to alternative models

### Chinese Character Encoding Issues

- Ensure your client is using UTF-8 encoding
- Check that the proxy is configured to handle UTF-8
- Verify that your terminal/client supports Chinese characters

## Integration with Coding Agents

Qwen works seamlessly with coding agents:

```bash
# Point your coding agent to the proxy
export OPENAI_API_BASE=http://localhost:8000/v1
export OPENAI_API_KEY=YOUR_PROXY_KEY

# Start the proxy with Qwen
python -m src.core.cli --default-backend qwen-oauth

# Your coding agent will now use Qwen models
```

## Hybrid Backend with Qwen

Qwen models work well in hybrid configurations. A tested combination:

```bash
# Use MiniMax for reasoning, Qwen for execution
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hybrid:[minimax:MiniMax-M2,qwen-oauth:qwen3-coder-plus]",
    "messages": [{"role": "user", "content": "Complex coding task"}]
  }'
```

See [Hybrid Backend](../features/hybrid-backend.md) for more details.

## Related Features

- [Model Name Rewrites](../features/model-name-rewrites.md) - Route models to Qwen
- [Hybrid Backend](../features/hybrid-backend.md) - Combine Qwen with other models
- [Edit Precision Tuning](../features/edit-precision.md) - Optimize for coding tasks

## Related Documentation

- [Backend Overview](overview.md)
- [ZAI Backend](zai.md)
- [OpenRouter Backend](openrouter.md)
