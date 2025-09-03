# LLM Interactive Proxy

This document provides an overview of the LLM Interactive Proxy, its features, API reference, and troubleshooting information.

## Overview

The LLM Interactive Proxy is an advanced middleware service that provides a unified interface to multiple Large Language Model (LLM) backends. It acts as an intelligent proxy layer between client applications and various LLM providers, offering enhanced features beyond simple request forwarding.

### Key Features

- **Multi-Backend Support**: Seamlessly integrate with OpenAI, Anthropic, Anthropic OAuth, Google Gemini, OpenRouter, custom backends, and Gemini CLI OAuth.
  - Included OAuth-style backends: Anthropic OAuth, OpenAI OAuth
- **Intelligent Failover**: Automatic fallback to alternative models/backends on failure.
- **Command Processing**: Interactive commands embedded in chat messages.
- **Rate Limiting**: Protect backends and manage usage quotas.
- **Session Management**: Maintain conversation state and context.
- **Loop Detection**: Prevent infinite loops in agent interactions (text and tool-call focused).
- **Tool Call Repair**: Converts malformed textual tool/function calls into OpenAI-compatible `tool_calls`.
- **JSON Repair**: Centralized in the streaming pipeline and enabled for non-streaming responses too. Uses `json_repair` library; supports schema validation and strict gating.
- **Unified API**: OpenAI-compatible API for all backends.
- **Empty Response Recovery**: Automatically detects empty LLM responses (no text, no tool call) and retries the request with a corrective prompt to guide the LLM.
- **Tool Call Reactor**: Event-driven system for reacting to tool calls from LLMs, with pluggable handlers that can provide steering instructions or modify responses.

### Error Mapping (API Behavior)

- Domain errors produced by the proxy are mapped to HTTP with a consistent JSON body:
  - `{ "error": { "message": str, "type": str, "code?": str, "details?": any } }`
- Connectivity failures (e.g., upstream connection issues) return `503 Service Unavailable`.
- Malformed JSON payloads return `400 Bad Request`.
- Validation errors return `422 Unprocessable Entity` and include validation `details`.

This makes client integrations easier to debug without inspecting server logs.

### Failover Strategy (optional)

- Two modes are available when a backend/model is unavailable:
  - Default: use the configured coordinator to produce fallback attempts.
  - Optional (flagged): enable a strategy that computes an ordered plan of `(backend, model)` attempts.
- Enable via config/flag (e.g., `PROXY_USE_FAILOVER_STRATEGY=true`). Default is disabled.

For internals and wiring details, see `CONTRIBUTING.md`.

#### Automated Edit-Precision Tuning (new)

- Detects failed file-edit attempts from popular coding agents (Cline, Roo/Kilo, Gemini-CLI, Aider, Crush, OpenCode) and automatically lowers sampling parameters for the next model call to improve literal matching and patch precision.
- Request-side detection: scans incoming user messages for known failure prompts (e.g., SEARCH/REPLACE no match, unified diff hunk failures).
- Optional response-side detection: inspects model responses (e.g., `diff_error`) and flags a one‑shot tuning for the next request.
- Single-call override only: tuned parameters apply to the very next backend call and then reset to normal.
- Config:
  - `edit_precision.enabled` (default: true)
  - `edit_precision.temperature` (default: 0.1)
  - `edit_precision.override_top_p` (default: false) and `edit_precision.min_top_p` (used only when override_top_p is true)
  - `edit_precision.override_top_k` (default: false) and `edit_precision.target_top_k` (used only when override_top_k is true, applied on providers that support `top_k`, e.g., Gemini)
  - `edit_precision.exclude_agents_regex` to disable tuning for specific agents (e.g., `^(cline|roocode)$`)
  - Patterns externalized at `conf/edit_precision_patterns.yaml`; override path with `EDIT_PRECISION_PATTERNS_PATH`.

- Env vars:
  - `EDIT_PRECISION_ENABLED` (true/false)
  - `EDIT_PRECISION_TEMPERATURE` (float)
  - `EDIT_PRECISION_OVERRIDE_TOP_P` (true/false)
  - `EDIT_PRECISION_MIN_TOP_P` (float)
  - `EDIT_PRECISION_OVERRIDE_TOP_K` (true/false)
  - `EDIT_PRECISION_TARGET_TOP_K` (integer; used only when override_top_k is true)
  - `EDIT_PRECISION_EXCLUDE_AGENTS_REGEX` (regex string)
  - `EDIT_PRECISION_PATTERNS_PATH` (file path to YAML patterns)

When does tuning trigger?

- LLMs often miss exact search/replace matches or produce ambiguous diffs. When an agent indicates a failure (e.g., “The SEARCH block … does not match”, “hunk failed to apply”), the proxy adjusts sampling (lower temperature, optionally lower top_p and top_k) to bias toward exact matches and reduce “creative” drift.

Backend semantics

- OpenAI-compatible (OpenAI/OpenRouter/ZAI/Qwen): applies top-level `temperature` and `top_p`.
- Anthropic-compatible: applies top-level `temperature` and `top_p` to Messages API.
- Gemini (all variants): applies `generationConfig.temperature` (clamped to [0,1] for public), `generationConfig.topP`, and, when configured, `generationConfig.topK`.

Logging

- Response-side detection logs when a trigger is matched (session id, pattern, new pending count).
- Request-side tuning logs when overrides are applied (session id, force_apply, original→applied `temperature`/`top_p`/`top_k`).
- Pending flag consumption logs the counter decrement before the tuned request is sent.

Triggers and sources

- Request-side: scans inbound messages (what the agent sends to the LLM) for known edit-failure prompts.
- Response-side: scans model output (non-streaming and streaming chunks) for failure markers such as `diff_error` and unified-diff hunk failures; sets a one-shot pending flag that tunes the very next request.
- Reference list of agent prompts captured from popular agents is maintained in `dev/agents-edit-error-prompts.md`.

### Wire-Level Capture (Request/Reply Logging)

- Purpose: Capture all outbound LLM requests and inbound replies/streams to a separate structured JSON log. Useful for debugging, auditing, and reproducing issues. The capture runs across all backends without backend-specific code.
- How it works:
  - Implemented as a cross-cutting `IWireCapture` service; integrated at the central backend call path.
  - Each communication is logged as a structured JSON object on a single line (JSON Lines format).
  - Communication flow is clearly marked (frontend_to_backend or backend_to_frontend) with source and destination.
  - Non-streaming responses are logged in full. Streaming responses are wrapped with start/chunk/end markers.
  - Includes ISO and human-readable timestamps based on local timezone.
  - Includes byte count for all payloads.
  - Automatically extracts and separately logs system prompts when present.
  - JSON schema available at [`src/core/services/wire_capture_schema.json`](src/core/services/wire_capture_schema.json).
- Enable via CLI: `--capture-file path/to/capture.log` (disabled by default). When omitted, no capture occurs.
- Configure via environment: set `CAPTURE_FILE` to a path to enable capture.
- Rotation and truncation options:
  - `CAPTURE_MAX_BYTES` (int): If set, rotates the current capture file to `<file>.1` when size would exceed this limit, then starts fresh. Rotation is best-effort and overwrites any existing `.1`.
  - `CAPTURE_TRUNCATE_BYTES` (int): If set, truncates each captured streaming chunk to this many bytes in the capture log. Stream data sent to the client is never truncated.

#### JSON Format Structure

Each captured message follows this JSON structure:

```json
{
  "timestamp": {
    "iso": "2023-06-15T13:45:30.123Z",
    "human_readable": "2023-06-15 15:45:30"
  },
  "communication": {
    "flow": "frontend_to_backend",  // or "backend_to_frontend"
    "direction": "request",  // or "response", "response_stream_start", "response_stream_chunk", "response_stream_end"
    "source": "127.0.0.1",  // Source of the message (client or backend)
    "destination": "openai"  // Destination of the message (backend or client)
  },
  "metadata": {
    "session_id": "user-session-123",
    "agent": "agent-name",
    "backend": "openai",
    "model": "gpt-4",
    "key_name": "OPENAI_API_KEY",
    "byte_count": 1024,
    "system_prompt": "You are a helpful assistant."  // If present in the request
  },
  "payload": {
    // The actual request or response payload
  }
}
```
  - `CAPTURE_MAX_FILES` (int): If set `> 0`, keeps up to N rotated files using suffixes `.1..N`. When rotation occurs, the oldest file is dropped and others are shifted.
  - CLI mirrors:
    - `--capture-max-bytes N`
    - `--capture-truncate-bytes N`
    - `--capture-max-files N`
- Example output:

```
----- REQUEST 2025-08-28T12:34:56Z -----
client=127.0.0.1 session=abc123 -> backend=openrouter model=gpt-4 key=OPENROUTER_API_KEY_1
{
  "model": "gpt-4",
  "messages": [
    {"role": "user", "content": "Hello"}
  ],
  "stream": true
}
----- REPLY-STREAM 2025-08-28T12:34:57Z -----
client=127.0.0.1 session=abc123 -> backend=openrouter model=gpt-4 key=OPENROUTER_API_KEY_1
data: {"choices":[{"delta":{"content":"Hi"}}]}

data: {"choices":[{"delta":{"content":" there"}}]}

data: [DONE]
```

Notes:

- Capture uses best-effort file I/O and never blocks or impacts request processing.
- API key “name” is derived by matching configured keys to env vars (e.g., `OPENROUTER_API_KEY_1`), never logging secret values.
- Redaction: if prompt redaction is enabled, capture contains post-redaction payloads.

### Security: API Key Redaction

- **Outbound Request Redaction**: Before any request reaches a backend, a request redaction middleware scans user message content (including text parts in multimodal messages) and replaces any discovered API keys with a placeholder `(API_KEY_HAS_BEEN_REDACTED)`. It also strips proxy commands (e.g., `!/hello`) to prevent command leakage to providers.
- **Logging Redaction**: A global logging filter automatically masks API keys and bearer tokens in all log messages and handler outputs.
- **Key Discovery**: Keys are discovered from `auth.api_keys`, `backends.<name>.api_key`, and environment variables (pattern-based, including `Bearer ...`).
- **Configuration**:
  - Enable/disable prompt redaction via `auth.redact_api_keys_in_prompts` (default: true).
  - CLI toggle: `--disable-redact-api-keys-in-prompts`.
- **Wire Capture Note**: If request/response wire capture is enabled, outbound requests are captured after redaction, so captured payloads are sanitized.

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

#### What you need (plain English)

- A Google account (Gmail or Google Workspace).
- A Google Cloud Project (a container for billing, APIs, and permissions).
- Billing enabled on that project.
- The Cloud AI Companion API enabled.
- One of these two authentication methods:
  - Option A: A Service Account key file (.json) with permissions on your project, or
  - Option B: Your own user account authenticated locally via gcloud (ADC).

Glossary:

- Service Account: A non-human identity used by apps/servers. You can create keys for it (JSON file) and grant it roles on your project.
- ADC (Application Default Credentials): A Google standard where tools pick credentials from your environment automatically (service account file, gcloud login, or workload identity).
- GOOGLE_CLOUD_PROJECT: The environment variable that specifies which GCP project to use (e.g., `my-project-123`).
- GOOGLE_APPLICATION_CREDENTIALS: The environment variable that points to a Service Account JSON file for ADC.

#### Step-by-step setup

1) Create or choose a Google Cloud Project

- Go to `https://console.cloud.google.com/`, create a project (note the Project ID, e.g., `my-project-123`).
- Ensure billing is enabled for the project.

2) Enable required API

```bash
gcloud services enable cloudaicompanion.googleapis.com --project=YOUR_PROJECT_ID
```

3) Grant permissions (to your user or to a service account)

Grant the role `roles/cloudaicompanion.user`.

- If you will authenticate as your own user (Option B):

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="user:YOUR_EMAIL@gmail.com" \
  --role="roles/cloudaicompanion.user"
```

- If you will use a Service Account (Option A):

```bash
# Create a service account (choose a name)
gcloud iam service-accounts create gemini-agent --project=YOUR_PROJECT_ID

# Grant it the required role
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:gemini-agent@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/cloudaicompanion.user"
```

4) Choose your authentication method

- Option A: Service Account (recommended for servers/CI)
  1. Create a JSON key for the service account:

  ```bash
  gcloud iam service-accounts keys create sa-key.json \
    --iam-account=gemini-agent@YOUR_PROJECT_ID.iam.gserviceaccount.com \
    --project=YOUR_PROJECT_ID
  ```

  2. Set environment variables so the backend can find the key and your project:
  - Windows PowerShell:

    ```powershell
    $env:GOOGLE_APPLICATION_CREDENTIALS = "C:\\path\\to\\sa-key.json"
    $env:GOOGLE_CLOUD_PROJECT = "YOUR_PROJECT_ID"
    ```

  - Linux/macOS:

    ```bash
    export GOOGLE_APPLICATION_CREDENTIALS="/absolute/path/sa-key.json"
    export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"
    ```

- Option B: Your User account via gcloud (local development)
  1. Install gcloud: `https://cloud.google.com/sdk/docs/install`
  2. Authenticate for Application Default Credentials (ADC):

  ```bash
  gcloud auth application-default login
  ```

  3. Tell the backend which project to use:
  - Windows PowerShell:

    ```powershell
    $env:GOOGLE_CLOUD_PROJECT = "YOUR_PROJECT_ID"
    ```

  - Linux/macOS:

    ```bash
    export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"
    ```

Notes:

- ADC means the backend will automatically pick credentials from either the service account file (`GOOGLE_APPLICATION_CREDENTIALS`) or your local gcloud login.
- Do not commit the `sa-key.json` file to source control.

5) Configure the backend (proxy)

- Using environment variables only:
  - Set `GOOGLE_CLOUD_PROJECT` as above.
  - If using a service account key, set `GOOGLE_APPLICATION_CREDENTIALS` as above.

- Using `config.yaml` (optional):

```yaml
backends:
  gemini-cli-cloud-project:
    type: gemini-cli-cloud-project
    gcp_project_id: YOUR_PROJECT_ID            # Optional if GOOGLE_CLOUD_PROJECT is set
    gemini_api_base_url: https://cloudcode-pa.googleapis.com
    # credentials_path: C:/path/sa-key.json    # Optional; if set, the backend will try this SA file first
```

6) Verify your setup

- Minimal check (env present):

```bash
echo $env:GOOGLE_CLOUD_PROJECT  # PowerShell
echo $GOOGLE_CLOUD_PROJECT      # bash/zsh
```

- Run the proxy or a small test that uses the `gemini-cli-cloud-project` backend and requests a simple completion. Ensure the first call may trigger onboarding (standard-tier) and might take a few seconds.

If you see 403 errors, double-check:

- Cloud AI Companion API is enabled.
- Billing is enabled.
- The identity (user or service account) has `roles/cloudaicompanion.user` on the project.
- `GOOGLE_CLOUD_PROJECT` matches your actual Project ID.

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

Additional tips:

- If using a service account, ensure the path in `GOOGLE_APPLICATION_CREDENTIALS` is absolute and accessible by the process.
- On Windows, use double backslashes in paths in PowerShell when setting env vars, or single backslashes inside quotes.
- For local development, `gcloud auth application-default login` is usually the fastest path; remember to set `GOOGLE_CLOUD_PROJECT` as well.

## Tool Call Reactor

The Tool Call Reactor is an event-driven system that allows you to react to tool calls made by LLMs in real-time. It provides a pluggable architecture for creating custom handlers that can monitor, modify, or replace tool call responses.

### Key Concepts

- **Event-Driven Architecture**: Handlers are triggered when LLMs make tool calls
- **Pluggable Handlers**: Create custom handlers for specific tool call patterns
- **Two Handler Modes**:
  - **Active Mode**: Can swallow tool calls and provide replacement responses
  - **Passive Mode**: Only observe tool calls without modifying responses
- **Rate Limiting**: Built-in rate limiting to prevent spam
- **Session Awareness**: Per-session state and rate limiting

### Built-in Handlers

#### Apply Diff Steering Handler

The `ApplyDiffHandler` monitors for `apply_diff` tool calls and provides steering instructions to use `patch_file` instead, which is considered superior due to automated QA checks.

**Features:**
- Monitors all `apply_diff` tool calls
- Rate limiting: Only provides steering once per minute per session
- Customizable steering message
- Session-aware rate limiting

**Example Response:**
```
You tried to use apply_diff tool. Please prefer to use patch_file tool instead, as it is superior to apply_diff and provides automated Python QA checks.
```

### Execution Order

The Tool Call Reactor is designed to run **after** other response processing middleware to ensure proper tool call handling:

1. **JSON Repair** → Fixes malformed JSON responses
2. **Tool Call Repair** → Converts plain-text tool calls to structured format
3. **Tool Call Loop Detection** → Prevents infinite loops
4. **Tool Call Reactor** → Applies custom handlers and steering logic

This order ensures that the reactor receives properly formatted tool calls and can focus on business logic rather than format repair.

### Configuration

The Tool Call Reactor is automatically enabled and configured in the proxy. The default `ApplyDiffHandler` is registered with:
- Rate limit: 1 steering message per 60 seconds per session
- Priority: 100 (high priority)
- Tool pattern: `apply_diff`

#### Environment Variables

- `TOOL_CALL_REACTOR_ENABLED=true|false` - Enable/disable the entire Tool Call Reactor system
- `APPLY_DIFF_STEERING_ENABLED=true|false` - Enable/disable the apply_diff steering handler
- `APPLY_DIFF_STEERING_RATE_LIMIT_SECONDS=60` - Rate limit window in seconds for steering messages
- `APPLY_DIFF_STEERING_MESSAGE="Custom message"` - Custom steering message (optional)

#### JSON/YAML Configuration

```json
{
  "session": {
    "tool_call_reactor": {
      "enabled": true,
      "apply_diff_steering_enabled": true,
      "apply_diff_steering_rate_limit_seconds": 60,
      "apply_diff_steering_message": "Custom steering message here"
    }
  }
}
```

```yaml
session:
  tool_call_reactor:
    enabled: true
    apply_diff_steering_enabled: true
    apply_diff_steering_rate_limit_seconds: 60
    apply_diff_steering_message: "Custom steering message here"
```

### Creating Custom Handlers

You can create custom handlers by implementing the `IToolCallHandler` interface:

```python
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)

class MyCustomHandler(IToolCallHandler):
    @property
    def name(self) -> str:
        return "my_custom_handler"

    @property
    def priority(self) -> int:
        return 50

    async def can_handle(self, context: ToolCallContext) -> bool:
        # Return True if this handler should process the tool call
        return context.tool_name == "my_tool"

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        # Process the tool call and return reaction
        return ToolCallReactionResult(
            should_swallow=True,
            replacement_response="Custom steering message",
            metadata={"handler": self.name}
        )
```

### Handler Registration

Handlers are registered through the DI container. To add a custom handler:

1. Create your handler class
2. Register it in the DI container in `src/core/di/services.py`
3. The handler will be automatically picked up by the reactor

### Use Cases

- **Tool Migration**: Guide users away from deprecated tools toward better alternatives
- **Security Filtering**: Block or modify potentially harmful tool calls
- **Usage Analytics**: Track and analyze tool call patterns
- **Quality Assurance**: Provide automated feedback on tool usage
- **Custom Workflows**: Implement domain-specific tool call processing

### Monitoring and Statistics

The Tool Call Reactor provides statistics through the reactor service:
- Total tool calls processed
- Tool calls swallowed by handlers
- Handler execution counts
- Rate limiting events
- Per-session statistics

## API Reference

The API is versioned using URL path prefixes:

- `/v1/` - Legacy API (compatible with OpenAI/Anthropic) - **REMOVED** (Use `/v2/` instead)
- `/v2/` - New SOLID architecture API (recommended and current)

All endpoints require authentication unless the server is started with `--disable-auth` or the request comes from a trusted IP address. Authentication is performed using the `Authorization` header with a bearer token: `Authorization: Bearer <api-key>`.

#### Trusted IP Addresses

The proxy supports bypassing authentication for requests originating from specified trusted IP addresses. This feature is useful for:
- Internal network access
- Load balancers or reverse proxies
- Development and testing environments
- CI/CD pipelines

**Command Line Usage:**
```bash
# Single trusted IP
./.venv/Scripts/python.exe -m src.core.cli --trusted-ip 192.168.1.100

# Multiple trusted IPs
./.venv/Scripts/python.exe -m src.core.cli --trusted-ip 192.168.1.100 --trusted-ip 10.0.0.50 --trusted-ip 172.16.0.100
```

**Configuration:**
```yaml
auth:
  trusted_ips:
    - "192.168.1.100"
    - "10.0.0.0/8"
    - "172.16.0.0/12"
```

**Notes:**
- CIDR notation is supported for IP ranges (e.g., `10.0.0.0/8`)
- Trusted IP bypass only applies when authentication is enabled (`--disable-auth` is not set)
- The proxy logs when authentication is bypassed for trusted IPs
- This feature does not affect API key validation for other security measures

Sessions are identified using the `x-session-id` header. If not provided, a new session ID will be generated.

### Endpoints

#### Chat Completions

- **Primary Endpoint (Recommended)**: `POST /v2/chat/completions`
- **Legacy Endpoint (Removed)**: `POST /v1/chat/completions`

#### Anthropic Messages API

- **Primary Endpoint (Recommended)**: `POST /v2/messages`
- **Legacy Endpoint (Removed)**: `POST /v1/messages`

#### Gemini API

- **Generate Content**: `POST /v2/models/{model}:generateContent`

#### Model Listing

- **OpenAI-Compatible Models**: `GET /v2/models`
- **Gemini Models**: `GET /v2/models/list`

#### Usage Statistics

- **Usage Stats**: `GET /v2/usage/stats`
- **Recent Usage**: `GET /v2/usage/recent`

#### Dedicated Anthropic Server

To accommodate clients that cannot use custom URI paths, the Anthropic front-end can be run on a dedicated port. When running on a dedicated port, the `/anthropic` path prefix is not required.

To run the dedicated Anthropic server, set the `ANTHROPIC_PORT` environment variable to the desired port number and run the following command:

```bash
python -m src.anthropic_server
```

#### Dedicated Anthropic Server

To accommodate clients that cannot use custom URI paths, the Anthropic front-end can be run on a dedicated port. When running on a dedicated port, the `/anthropic` path prefix is not required.

To run the dedicated Anthropic server, set the `ANTHROPIC_PORT` environment variable to the desired port number and run the following command:

```bash
python -m src.anthropic_server
```

If the `ANTHROPIC_PORT` is not set, it will default to the main port + 1.

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

### JSON Repair

- **What it does**: Automatically detects and repairs malformed JSON in model responses. Can optionally validate and coerce data into a target schema (JSON Schema). Works for both non-streaming and streaming pipelines.
- **Detection & Repair**: Prefers fenced ```json blocks, otherwise scans for balanced braces. Repairs common issues like single quotes, trailing commas, unbalanced braces/brackets, and stray control characters.
- **Schema Coercion**: Using jsonschema with coercion (e.g., "42" → 42). Supports type coercion, defaults injection, and unknown property handling.
- **Enable/disable**: Controlled via config and env vars (see below). Enabled by default.
- **Buffer cap**: Per-session buffer is limited (default 64 KB). Increase only if your JSON payloads are unusually large.

#### Configuration

- Config path: `AppConfig.session`
- `json_repair_enabled` (bool, default `true`)
- `json_repair_buffer_cap_bytes` (int, default `65536`)
- `json_repair_strict_mode` (bool, default `false`)
- `json_coercion_enabled` (bool, default `true`)
- `json_schema_sources` (dict[str, Any], default `{}`)

- Environment variables
  - `JSON_REPAIR_ENABLED=true|false`
  - `JSON_REPAIR_BUFFER_CAP_BYTES=65536`
  - `JSON_REPAIR_STRICT_MODE=true|false`
  - `JSON_COERCION_ENABLED=true|false`

Example (YAML-like):

```yaml
session:
  json_repair_enabled: true
  json_repair_buffer_cap_bytes: 65536
  json_repair_strict_mode: false
  json_coercion_enabled: true
 json_schema_sources: {}
```

Notes:

- Repair is conservative and only activates when patterns are confidently detected. If detection fails, the response is passed through unchanged.
- For streaming, trailing free text immediately after a repaired JSON is not emitted by default to avoid ambiguity.
- Schema coercion can be enabled/disabled independently of JSON repair.

### Rate Limiting Issues

- **Rate Limit Exceeded**: Check rate limit configuration, use multiple API keys, implement backoff and retry logic.
- **Uneven API Key Usage**: Use round-robin policy for API keys, configure failover routes.

### Performance Problems

- **High Latency**: Use faster models, monitor performance with tracking, enable response caching.
- **Memory Leaks**: Limit session history, implement session expiry, monitor memory usage.

## Support

- Issues: [GitHub Issues](https://github.com/your-org/llm-interactive-proxy/issues)
- Changelog: [CHANGELOG.md](CHANGELOG.md)

## Processing & Repair Pipeline

- **Streaming order**: JSON repair → text loop detection → tool-call repair → middleware → accumulation. This order ensures:
  - Loop detection runs on human-visible text, avoiding false positives from JSON scaffolding.
  - Tool-call repair operates after normalization.

- **Non-streaming repairs**:
  - JSON repair and tool-call repair are applied via middleware on final content.
  - Tool-call loop detection middleware can stop repeated tool calls (configurable; defaults enabled).

### JSON Repair Strict Mode (Non-Streaming)

- Strict mode is enabled when any of the following are true:
  - `session.json_repair_strict_mode` is true (global opt-in)
  - Response Content-Type is `application/json`
  - `expected_json=True` is set in response metadata (see helpers below)
  - A `session.json_repair_schema` is configured

- Otherwise, repairs are best-effort: failures don’t raise and original content is preserved.

### Convenience Helpers (expected_json)

- Location: `src/core/utils/json_intent.py`
  - `set_expected_json(metadata, True)`: marks a non-streaming response as JSON for strict repair
  - `infer_expected_json(metadata, content)`: detects JSON intent from Content-Type or JSON-looking content
  - `set_json_response_metadata(metadata, content_type='application/json; charset=utf-8')`: sets Content-Type and expected_json in one call

- The proxy auto-inferrs `expected_json` for non-streaming responses if not provided, based on Content-Type or payload shape. You can always override by calling `set_expected_json` on response metadata in controllers/adapters.

### Metrics

- Module: `src/core/services/metrics_service.py` (in-memory counters)
- Counters recorded:
  - `json_repair.streaming.[strict|best_effort]_{success|fail}`
  - `json_repair.non_streaming.[strict|best_effort]_{success|fail}`

### Tool-Call Loop Detection

- Detects 4 identical tool calls (same name + args) in a row within a TTL; sends guidance (chance) or breaks based on mode.
- Configurable with `LoopDetectionConfiguration` and `ToolCallLoopConfig`.

### Anthropic OAuth Backend

The `anthropic-oauth` backend enables Anthropic usage without placing API keys in your proxy config. It reads a local OAuth-style credential file (commonly produced by tools like Claude Code) and uses its token as the `x-api-key`.

Key points:
- Credentials file name: `oauth_creds.json`
- Default search paths (first found wins):
  - Windows: `%APPDATA%/Claude/oauth_creds.json`
  - Cross‑platform: `~/.anthropic/oauth_creds.json`, `~/.claude/oauth_creds.json`, `~/.config/claude/oauth_creds.json`
- Expected fields: `access_token` (preferred) or `api_key`
- Base URL default: `https://api.anthropic.com/v1` (override with `anthropic_api_base_url`)

Configuration (config.yaml):

```yaml
backends:
  anthropic-oauth:
    type: anthropic-oauth
    # Optional: directory path that contains oauth_creds.json
    anthropic_oauth_path: C:\\Users\\YourUser\\.anthropic
    # Optional: override Anthropic API base URL
    anthropic_api_base_url: https://api.anthropic.com/v1

  # Example alongside other backends
  openai:
    type: openai
    api_key: sk-...

# Optional: make anthropic-oauth the default backend for the proxy
# backends:
#   default_backend: anthropic-oauth
```

Environment and routing:
- Set `LLM_BACKEND=anthropic-oauth` to select it at startup.
- Route per-request via model name prefix: `model: anthropic-oauth:claude-3-5-sonnet-20241022`.

Environment variable alternative:
- You can override the Anthropic base URL using `ANTHROPIC_API_BASE_URL` instead of the YAML field `anthropic_api_base_url`.

Troubleshooting:
- 401/403: Ensure `oauth_creds.json` exists in a default path or set `anthropic_oauth_path` to its directory.
- Invalid credentials: File must contain `access_token` or `api_key`.
- Model names: Use Anthropic Messages API models (e.g., `claude-3-5-sonnet-20241022`).

### OpenAI OAuth Backend

The `openai-oauth` backend lets you use OpenAI without storing an API key in your proxy config. It reads the ChatGPT/Codex `auth.json` file created by the Codex CLI and uses the contained token as the `Authorization: Bearer ...` header for OpenAI API calls.

Key points:
- Credentials file name: `auth.json`
- Default search paths (first found wins):
  - Windows: `%USERPROFILE%/.codex/auth.json`
  - Cross‑platform: `~/.codex/auth.json`
- Token priority: `tokens.access_token` (preferred), then `OPENAI_API_KEY` as fallback
- Base URL default: `https://api.openai.com/v1` (override with `openai_api_base_url` or env `OPENAI_BASE_URL` if your environment uses one)

Configuration (config.yaml):

```yaml
backends:
  openai-oauth:
    type: openai-oauth
    # Optional: directory path that contains auth.json
    openai_oauth_path: C:\\Users\\YourUser\\.codex
    # Optional: override OpenAI API base URL
    openai_api_base_url: https://api.openai.com/v1

  # Example alongside other backends
  openai:
    type: openai
    api_key: sk-...

# Optional: make openai-oauth the default backend for the proxy
# backends:
#   default_backend: openai-oauth
```

Environment and routing:
- Set `LLM_BACKEND=openai-oauth` to select it at startup.
- Route per-request via model name prefix: `model: openai-oauth:gpt-4o-mini`.

Troubleshooting:
- 401/403: Ensure `auth.json` exists in a default path or set `openai_oauth_path` to its directory.
- Invalid credentials: File must contain `tokens.access_token` or `OPENAI_API_KEY`.
### Content Rewriting

The LLM Interactive Proxy provides a powerful content rewriting feature that allows you to modify incoming and outgoing messages on the fly. This functionality is configured through a simple directory structure and supports several rewriting modes.

#### Directory Structure

The content rewriting rules are defined in the `config/replacements` directory. The structure is as follows:

```
config/
└── replacements/
    ├── prompts/
    │   ├── system/
    │   │   └── 001/
    │   │       ├── SEARCH.txt
    │   │       └── REPLACE.txt
    │   └── user/
    │       └── 001/
    │           ├── SEARCH.txt
    │           └── APPEND.txt
    └── replies/
        └── 001/
            ├── SEARCH.txt
            └── PREPEND.txt
```

- **`prompts`**: Contains rules for rewriting outgoing prompts.
  - **`system`**: Rules for system-level prompts.
  - **`user`**: Rules for user-level prompts.
- **`replies`**: Contains rules for rewriting incoming replies from the LLM.

Each rule is defined in its own numbered subdirectory (e.g., `001`, `002`).

#### Rewriting Modes

The content rewriting feature supports the following modes:

- **`REPLACE`**: Replaces the content of `SEARCH.txt` with the content of `REPLACE.txt`.
- **`PREPEND`**: Prepends the content of `PREPEND.txt` to the content of `SEARCH.txt`.
- **`APPEND`**: Appends the content of `APPEND.txt` to the content of `SEARCH.txt`.

Each rule directory must contain a `SEARCH.txt` file and one of the mode files (`REPLACE.txt`, `PREPEND.txt`, or `APPEND.txt`).

#### Sanity Checks

To ensure the quality of the rewriting rules, the following sanity checks are in place:

- **Search Pattern Length**: The content of `SEARCH.txt` must be at least 8 characters long. Rules with shorter search patterns will be ignored.
- **Unique Mode Files**: Each rule directory can only contain one mode file. If multiple mode files are found, the rule will be ignored.

#### Examples

**Example 1: Replacing a system prompt**

- `config/replacements/prompts/system/001/SEARCH.txt`:
  ```
  You are a helpful assistant.
  ```
- `config/replacements/prompts/system/001/REPLACE.txt`:
  ```
  You are a very helpful assistant.
  ```

**Example 2: Appending to a user prompt**

- `config/replacements/prompts/user/001/SEARCH.txt`:
  ```
  What is the weather in London?
  ```
- `config/replacements/prompts/user/001/APPEND.txt`:
  ```
  in Celsius
  ```

**Example 3: Prepending to a reply**

- `config/replacements/replies/001/SEARCH.txt`:
  ```
  The weather in London is 20 degrees.
  ```
- `config/replacements/replies/001/PREPEND.txt`:
  ```
  According to my sources, 
  ```
# Test change
