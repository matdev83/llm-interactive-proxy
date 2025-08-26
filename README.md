# LLM Interactive Proxy

This document provides an overview of the LLM Interactive Proxy, its features, API reference, and troubleshooting information.

## Overview

The LLM Interactive Proxy is an advanced middleware service that provides a unified interface to multiple Large Language Model (LLM) backends. It acts as an intelligent proxy layer between client applications and various LLM providers, offering enhanced features beyond simple request forwarding.

### Key Features

- **Multi-Backend Support**: Seamlessly integrate with OpenAI, Anthropic, Google Gemini, OpenRouter, custom backends, and Gemini CLI OAuth.
- **Intelligent Failover**: Automatic fallback to alternative models/backends on failure.
- **Command Processing**: Interactive commands embedded in chat messages.
- **Rate Limiting**: Protect backends and manage usage quotas.
- **Session Management**: Maintain conversation state and context.
- **Loop Detection**: Prevent infinite loops in agent interactions.
- **Tool Call Repair**: Automatically repairs malformed tool/function calls emitted as plain text.
- **Unified API**: OpenAI-compatible API for all backends.

## Backend Support

### Gemini Backends Overview

The proxy supports three different Gemini backends, each with its own authentication method and use case:

| Backend | Authentication | Cost | Best For |
|---------|---------------|------|
----------|
| `gemini` | API Key | Pay-per-use (metered) | Production apps, high-volume usage |
| `gemini-cli-oauth-personal` | OAuth 2.0 (free tier) | Free with limits | Development, testing, personal projects |
| `gemini-cli-cloud-project` | OAuth 2.0 + GCP Project | Billed to GCP project | Enterprise, production with GCP integration |
#### Key Differences

**Gemini (API Key)**
- **Setup**: Requires a Google AI Studio API key from [makersuite.google.com](https://makersuite.google.com/app/apikey)
- **Billing**: Pay-as-you-go pricing based on tokens used
- **Limits**: Higher rate limits and quotas
- **Models**: Access to all Gemini models including latest releases
- **Use Case**: Production applications, commercial projects

**Gemini CLI OAuth Personal**
- **Setup**: Uses OAuth credentials from the Gemini CLI tool (no API key needed)
- **Billing**: Free tier with usage limits (uses Google-managed project)
- **Limits**: Lower rate limits suitable for development
- **Models**: Access to Gemini models through Code Assist API
- **Use Case**: Personal projects, development, testing, learning

**Gemini CLI Cloud Project**
- **Setup**: OAuth credentials + your own Google Cloud Project ID
- **Billing**: Usage billed to your GCP project (standard or enterprise tier)
- **Limits**: Higher quotas based on your GCP project settings
- **Models**: Access to all Code Assist API models with enterprise features
- **Use Case**: Production apps with GCP integration, enterprise deployments

### Gemini CLI OAuth Personal Backend

The `gemini-cli-oauth-personal` backend provides seamless integration with Google's Gemini API using OAuth 2.0 credentials obtained through the Gemini CLI tool. This backend is ideal for developers who want to use Gemini without setting up billing or managing API keys.

#### Prerequisites

1. **Install Gemini CLI**: Install the Gemini CLI tool from [Google's official repository](https://github.com/google/gemini-cli)
2. **Authenticate**: Run `gemini auth` to authenticate with Google and obtain OAuth credentials
3. **Credential Storage**: The CLI will create `~/.gemini/oauth_creds.json` with your OAuth tokens

#### Configuration

Add to your `config.yaml`:

```yaml
backends:
  # For OAuth-based authentication (free tier)
  gemini-cli-oauth-personal:
    type: gemini-cli-oauth-personal
    gemini_api_base_url: https://cloudcode-pa.googleapis.com  # Code Assist endpoint
    
  # For OAuth with your own GCP project (billed to project)
  gemini-cli-cloud-project:
    type: gemini-cli-cloud-project
    gcp_project_id: your-gcp-project-id  # Required: Your GCP project ID
    credentials_path: ~/.gemini  # Optional: Path to credentials directory
    gemini_api_base_url: https://cloudcode-pa.googleapis.com
    
  # For API key-based authentication (paid/metered)
  gemini:
    type: gemini
    api_key: your-gemini-api-key  # From Google AI Studio
    gemini_api_base_url: https://generativelanguage.googleapis.com
```

#### Usage

```bash
# For OAuth backend (free tier)
!/backend(gemini-cli-oauth-personal)
!/model(gemini-1.5-flash-002)  # Use Code Assist model names

# For OAuth with GCP project (billed to project)
!/backend(gemini-cli-cloud-project)
!/model(gemini-1.5-flash-002)  # Use Code Assist model names

# For API key backend (paid)
!/backend(gemini)
!/model(gemini-1.5-pro)  # Use standard Gemini model names

# Or use with one-off requests
!/oneoff(gemini-cli-oauth-personal:gemini-1.5-flash-002)
!/oneoff(gemini-cli-cloud-project:gemini-1.5-flash-002)
!/oneoff(gemini:gemini-1.5-pro)
```

#### Features

- **Zero-Cost Development**: Use Gemini's free tier without setting up billing
- **Automatic Token Refresh**: Handles OAuth token expiration automatically
- **Health Checks**: Performs lightweight connectivity and authentication validation
- **Error Handling**: Comprehensive error handling for authentication and API issues
- **Cross-Platform**: Works on Windows, Linux, and macOS
- **No API Key Management**: Eliminates the need to manage and secure API keys

#### Troubleshooting

- **Authentication Errors**: Ensure `~/.gemini/oauth_creds.json` exists and contains valid tokens
- **Model Not Found**: Use Code Assist model names (e.g., `gemini-1.5-flash-002`) not standard names
- **Rate Limits**: Free tier has lower limits; consider switching to API key backend for production
- **Token Expiration**: The backend handles refresh automatically; manual re-authentication is rarely needed

### Gemini CLI Cloud Project Backend

The `gemini-cli-cloud-project` backend provides enterprise-grade integration with Google Cloud Platform, using your own GCP project for billing and quota management. This backend is ideal for production deployments where you need:

- Full control over billing and usage
- Higher quotas than free tier
- Integration with existing GCP infrastructure
- Enterprise support and SLAs

#### Prerequisites

1. **Google Cloud Project**: Create or use an existing GCP project with billing enabled
2. **Enable APIs**: Enable the Cloud AI Companion API in your GCP project
3. **IAM Permissions**: Ensure you have `roles/cloudaicompanion.user` or equivalent
4. **Authenticate**: Run `gemini auth` to obtain OAuth credentials (same as personal backend)
5. **Project ID**: Note your GCP project ID (e.g., `my-project-123`)

#### How to Use

1. **Set up your GCP Project**:
   ```bash
   # Enable Cloud AI Companion API in your project
   gcloud services enable cloudaicompanion.googleapis.com --project=YOUR_PROJECT_ID
   
   # Verify billing is enabled
   gcloud beta billing projects describe YOUR_PROJECT_ID
   
   # Grant yourself the necessary IAM role (if not already granted)
   gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
     --member="user:YOUR_EMAIL@gmail.com" \
     --role="roles/cloudaicompanion.user"
   ```

2. **Authenticate with Gemini CLI**:
   ```bash
   # Install gemini CLI if not already installed
   npm install -g @google/gemini-cli
   
   # Authenticate to get OAuth credentials
   gemini auth
   ```

3. **Configure the backend**:
   
   Set environment variables:
   ```bash
   export GCP_PROJECT_ID=your-gcp-project-id
   export GEMINI_CREDENTIALS_PATH=~/.gemini  # Optional
   ```
   
   Or add to your `config.yaml`:
   ```yaml
   backends:
     gemini-cli-cloud-project:
       type: gemini-cli-cloud-project
       gcp_project_id: your-gcp-project-id  # Your actual GCP project ID
       credentials_path: ~/.gemini          # Optional: defaults to ~/.gemini
       gemini_api_base_url: https://cloudcode-pa.googleapis.com
   ```

4. **Test the setup**:
   ```bash
   # Run the test script to verify everything works
   python test_cloud_project.py --project YOUR_PROJECT_ID
   ```

5. **Use in your application**:
   ```bash
   # Set the backend for your session
   !/backend(gemini-cli-cloud-project)
   !/model(gemini-1.5-flash-002)
   
   # Or use as a one-off
   !/oneoff(gemini-cli-cloud-project:gemini-1.5-flash-002)
   ```

#### Key Differences from Other Backends

| Aspect | Cloud Project | Personal OAuth | API Key |
|--------|--------------|----------------|---------|
| **Project** | Your GCP project | Google-managed | N/A |
| **Billing** | To your GCP account | Free (limited) | Pay-per-use |
| **Tier** | standard/enterprise | free-tier | N/A |
| **Quotas** | Project-defined | Limited | API-defined |
| **Setup** | GCP project + OAuth | OAuth only | API key only |

#### Troubleshooting Cloud Project Backend

- **403 Permission Denied**: Enable Cloud AI Companion API, check IAM permissions, verify billing
- **Project Not Found**: Verify project ID (not name), ensure project is active
- **Onboarding Fails**: Project must support standard-tier, billing must be enabled
- **Wrong Tier**: Backend requires standard or enterprise tier, not free tier

## API Reference

The API is versioned using URL path prefixes:

- `/v1/` - Legacy API (compatible with OpenAI/Anthropic) - **DEPRECATED**
- `/v2/` - New SOLID architecture API (recommended)

All endpoints require authentication unless the server is started with `--disable-auth`. Authentication is performed using the `Authorization` header with a bearer token: `Authorization: Bearer <api-key>`.

Sessions are identified using the `x-session-id` header. If not provided, a new session ID will be generated.

### Endpoints

#### Chat Completions

- **Primary Endpoint (Recommended)**: `POST /v2/chat/completions`
- **Legacy Endpoint (Deprecated)**: `POST /v1/chat/completions`

#### Anthropic Messages API

- **Primary Endpoint (Recommended)**: `POST /v2/messages`
- **Legacy Endpoint (Deprecated)**: `POST /v1/messages`

#### Gemini API

- **Generate Content**: `POST /v2/models/{model}:generateContent`

#### Model Listing

- **OpenAI-Compatible Models**: `GET /v2/models`, `GET /v1/models` (Deprecated)
- **Gemini Models**: `GET /v2/models/list`

#### Usage Statistics

- **Usage Stats**: `GET /v2/usage/stats`
- **Recent Usage**: `GET /v2/usage/recent`

#### Audit Logs

- `GET /v2/audit/logs`

## In-Chat Commands

The LLM Interactive Proxy supports in-chat commands that can be used to control the proxy's behavior. Commands are prefixed with `!/` by default.

### Core Commands

| Command | Description | Example |
|---------|-------------|---------|
| `!/hello` | Shows welcome message and session info | `!/hello` |
| `!/help` | Shows available commands | `!/help` |
| `!/set` | Sets a session parameter | `!/set(project=myproject)` |
| `!/unset` | Unsets a session parameter | `!/unset(project)` |
| `!/backend` | Sets backend for the session | `!/backend(openai)` |
| `!/model` | Sets model for the session | `!/model(gpt-4)` |
| `!/oneoff` | Sets backend and model for one request | `!/oneoff(anthropic:claude-3)` |
| `!/interactive` | Toggles interactive mode | `!/interactive(true)` |
| `!/temperature` | Sets temperature for generation | `!/temperature(0.7)` |
| `!/pwd` | Shows current project directory | `!/pwd` |

### Failover Commands

| Command | Description | Example |
|---------|-------------|---------|
| `!/route-list` | Lists configured routes | `!/route-list` |
| `!/route-clear` | Clears a route | `!/route-clear(gpt-4)` |
| `!/route-append` | Appends a route | `!/route-append(gpt-4, anthropic:claude-3)` |
| `!/route-prepend` | Prepends a route | `!/route-prepend(gpt-4, openai:gpt-3.5-turbo)` |

## Troubleshooting

### Installation Issues

- **Package Installation Fails**: Ensure Python version compatibility (3.9+), create a fresh virtual environment, install with verbose output (`pip install -e ".[dev]" -v`), check for system dependencies.
- **Import Errors After Installation**: Verify package is installed in development mode (`pip list | grep llm-interactive-proxy`), check `PYTHONPATH`, reinstall.

### Configuration Problems

- **Missing or Invalid Configuration**: Create/verify `config.yaml`, set required environment variables, check configuration path, validate format.
- **Backend Configuration Problems**: Check `backends` section in `config.yaml`, verify API keys, set default backend.
- **Gemini API Key Issues**: Ensure API key is valid from Google AI Studio, check for typos, verify billing is enabled.
- **Gemini CLI OAuth Issues**: Verify `~/.gemini/oauth_creds.json` exists and contains valid tokens, ensure Gemini CLI is properly authenticated, use correct Code Assist model names.

### API Authentication Issues

- **Unauthorized Access**: Check `Authorization` header format (`Bearer <api-key>`), disable authentication for testing (`--disable-auth`), verify API key in configuration.
- **Invalid API Key Format**: Check API key format for specific backend (e.g., OpenAI starts with "sk-"), remove whitespace or quotes.

### Backend Connection Problems

- **Connection Timeout**: Increase timeout settings in `config.yaml` (`proxy_timeout`), check network connectivity, use proxy if needed.
- **Invalid Backend or Model**: List available models (`curl http://localhost:8000/v2/models`), check model format (e.g., `openai:gpt-4`), specify backend and model explicitly.

### Command Processing Errors

- **Commands Not Recognized**: Check command prefix (`!/`), verify command format (`!/set(project=myproject)`), enable interactive mode, ensure interactive commands are not disabled.
- **Command Arguments Not Parsed Correctly**: Check argument syntax (no spaces around `=`), quote string values with spaces, use proper comma separation.

### Session Management Issues

- **Session State Not Persisting**: Provide `x-session-id` header in requests, check session repository configuration (`in_memory` vs `file`), use persistent session repository.
- **Session ID Conflicts**: Use unique session IDs (e.g., UUIDs), namespace session IDs for different clients.

### Streaming Response Problems

- **Streaming Responses Not Working**: Set `stream` parameter to `true` in request, check client streaming support (SSE), disable response buffering.
- **Streaming Responses Cut Off**: Increase proxy timeout, increase client timeout, check for network issues.

### Loop Detection Issues

- **False Positives in Loop Detection**: Adjust `min_pattern_length`, `max_pattern_length`, `min_repetitions` in `loop_detection` config, disable for specific sessions, tune thresholds.
- **Loop Detection Not Working**: Enable loop detection in `config.yaml`, check `min_pattern_length`, verify middleware registration.

### Tool Call Loop Detection Problems

- **Tool Call Loops Not Detected**: Enable tool call loop detection in `config.yaml`, set session-level configuration, check tool call format.
- **False Positives in Tool Call Loop Detection**: Increase `max_repeats`, use `chance_then_block` mode, increase `ttl_seconds`.

### Tool Call Repair

- **What it does**: Some providers or model outputs occasionally return tool/function calls as plain text instead of structured `tool_calls`. The proxy detects common patterns (JSON objects, code blocks, or textual directives like "TOOL CALL: ...") and converts them to proper OpenAI-style `tool_calls` before returning to the client.
- **Non-streaming**: Repair runs on complete responses and updates `choices[0].message` with `tool_calls` and `finish_reason="tool_calls"` while clearing conflicting `content`.
- **Streaming**: A streaming repair processor accumulates minimal context to detect and emit `tool_calls` safely. The buffer is capped to prevent memory growth.
- **Enable/disable**: Controlled via config and env vars (see below). Enabled by default.
- **Buffer cap**: Per-session buffer is limited (default 64 KB). Increase only if your tool-call payloads are unusually large.

#### Configuration

- Config path: `AppConfig.session`
  - `tool_call_repair_enabled` (bool, default `true`)
  - `tool_call_repair_buffer_cap_bytes` (int, default `65536`)

- Environment variables
  - `TOOL_CALL_REPAIR_ENABLED=true|false`
  - `TOOL_CALL_REPAIR_BUFFER_CAP_BYTES=65536`

Example (YAML-like):

```yaml
session:
  tool_call_repair_enabled: true
  tool_call_repair_buffer_cap_bytes: 65536
```

Notes:

- Repair is conservative and only activates when patterns are confidently detected. If detection fails, the response is passed through unchanged.
- For streaming, trailing free text immediately after a repaired tool call is not emitted by the repair processor to avoid ambiguity; the client will see the repaired tool call with `finish_reason="tool_calls"`.

### Rate Limiting Issues

- **Rate Limit Exceeded**: Check rate limit configuration, use multiple API keys, implement backoff and retry logic.
- **Uneven API Key Usage**: Use round-robin policy for API keys, configure failover routes.

### Performance Problems

- **High Latency**: Use faster models, monitor performance with tracking, enable response caching.
- **Memory Leaks**: Limit session history, implement session expiry, monitor memory usage.

## Support

- Issues: [GitHub Issues](https://github.com/your-org/llm-interactive-proxy/issues)
