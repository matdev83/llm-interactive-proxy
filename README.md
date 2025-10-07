# LLM Interactive Proxy

![CI](https://img.shields.io/github/actions/workflow/status/matdev83/llm-interactive-proxy/ci.yml?branch=main&event=push&label=CI&cacheSeconds=300)
![Architecture Check](https://img.shields.io/github/actions/workflow/status/matdev83/llm-interactive-proxy/architecture-check.yml?branch=main&event=push&label=Architecture&cacheSeconds=300)
[![Coverage](https://img.shields.io/codecov/c/github/matdev83/llm-interactive-proxy?branch=main&token=)](https://codecov.io/gh/matdev83/llm-interactive-proxy)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![License](https://img.shields.io/github/license/matdev83/llm-interactive-proxy?color=blue)](LICENSE)
![Last Commit](https://img.shields.io/github/last-commit/matdev83/llm-interactive-proxy?label=Last%20commit)
![Open Issues](https://img.shields.io/github/issues/matdev83/llm-interactive-proxy?label=Open%20issues)

This project is a swiss-army knife for anyone working with language models and agentic workflows. It sits between any LLM-aware client and any LLM backend, presenting multiple front-end APIs (OpenAI, Anthropic, Gemini) while routing to whichever provider you choose. With the proxy you can translate, reroute, and augment requests on the fly, execute chat-embedded commands, override models, rotate API keys, prevent leaks, and inspect traffic -- all from a single drop-in gateway.

## Contents

- [Use Cases](#use-cases)
- [Killer Features](#killer-features)
- [Supported APIs (Front-Ends) and Providers (Back-Ends)](#supported-apis-front-ends-and-providers-back-ends)
- [Gemini Backends Overview](#gemini-backends-overview)
- [Quick Start](#quick-start)
- [Using It Day-To-Day](#using-it-day-to-day)
- [Security](#security)
- [Debugging (Wire Capture)](#debugging-wire-capture)
- [Optional Capabilities (Short List)](#optional-capabilities-short-list)
- [Example Config (minimal)](#example-config-minimal)
- [Popular Scenarios](#popular-scenarios)
- [Errors and Troubleshooting](#errors-and-troubleshooting)
- [Running Tests](#running-tests)
- [Support](#support)
- [License](#license)
- [Changelog](#changelog)

## Use Cases

- **Connect Any App to Any Model**: Seamlessly route requests from any LLM-powered application to any model, even across different protocols. Use clients like Anthropic's Claude Code CLI with a Gemini 2.5 Pro model, or Codex CLI with a Kimi K2 model.
- **Structured JSON Output**: Use the OpenAI Responses API for guaranteed JSON output that conforms to a specific schema, with automatic validation and repair.
- **Override Hardcoded Models**: Force an application to use a model of your choice, even if the developers didn't provide an option to change it.
- **Inspect and Debug Prompts**: Capture and analyze the exact prompts your agent sends to the LLM provider to debug and refine interactions.
- **Customize System Prompts**: Rewrite or modify an agent's system prompt to better suit your specific needs and improve its performance.
- **Leverage Your LLM Subscriptions**: Use your personal subscriptions, like OpenAI Plus/Pro or Anthropic Pro/MAX plans, with any third-party application, not just those developed by the LLM vendor.
- **Automated Model Tuning for Precision**: The proxy automatically detects when a model struggles with tasks like precise file edits and adjusts its parameters to improve accuracy on subsequent attempts. **Configuration (precedence: CLI > Env > YAML)**:
  - **CLI Flags**:
    - `--enable-edit-precision` / `--disable-edit-precision`: Enable or disable edit-precision tuning
    - `--edit-precision-temperature FLOAT`: Set target temperature for edit failures (default: 0.1)
    - `--edit-precision-min-top-p FLOAT`: Set minimum top_p value for edit failures (default: 0.3)
    - `--edit-precision-override-top-p`: Enable top_p override for edit failures
    - `--edit-precision-exclude-agents REGEX`: Exclude specific agents from edit-precision tuning
  - **Environment Variables**:
    - `EDIT_PRECISION_ENABLED=true|false` (default: true)
    - `EDIT_PRECISION_TEMPERATURE=0.1` (default: 0.1)
    - `EDIT_PRECISION_MIN_TOP_P=0.3`
    - `EDIT_PRECISION_OVERRIDE_TOP_P=false|true`
    - `EDIT_PRECISION_EXCLUDE_AGENTS_REGEX="<pattern>"`
  - **YAML** (`config.yaml`):
    ```yaml
    edit_precision:
      enabled: true
      temperature: 0.1
      min_top_p: 0.3
      override_top_p: false
      exclude_agents_regex: null
    ```
- **Model Name Rewrites (NEW)**: Dynamically rewrite model names using powerful regex-based rules. Route all GPT requests to OpenRouter, replace specific models with alternatives, or create catch-all fallbacks - all configurable via CLI, environment variables, or config files.
- **Planning-Phase Strong Model Overrides (NEW)**: Optionally route the first part of a session to a stronger model and override its parameters (e.g., temperature, top_p, reasoning effort, thinking budget) to maximize planning quality; automatically switch back to the default model after a set number of turns or file writes.
- **Automatic Tool Call Repair**: If a model generates invalid tool calls, the proxy automatically corrects them before they can cause errors in your agent.
- **Automated Error Detection and Steering**: Detect when an LLM is stuck in a loop or fails to follow instructions, and automatically generate steering commands to get it back on track.
- **Block Harmful Tool Calls**: Prevent potentially destructive actions, such as deleting your git repository, by detecting and blocking harmful tool calls at the proxy level.
- **Maximize Free Tiers with API Key Rotation**: Aggregate all your API keys and use auto-rotation to seamlessly switch between them, allowing you to take full advantage of multiple free-tier allowances.

## Killer Features

### Compatibility

- Multiple front-ends, many providers: exposes OpenAI, Anthropic, and Gemini APIs while routing to OpenAI, Anthropic, Gemini, OpenRouter, ZAI, Qwen, and more
- **OpenAI Responses API**: Full support for the `/v1/responses` endpoint, enabling structured JSON output with schema validation.
- **Protocol Translation**: A powerful translation service that converts requests and responses between different API formats (e.g., OpenAI to Anthropic, Gemini to OpenAI).
- OpenAI compatibility: drop-in `/v1/chat/completions` for most clients and coding agents
- Streaming everywhere: consistent streaming and non-streaming support across providers
- Gemini OAuth personal gateway: use Google's free personal OAuth (CLI-style) through an OpenAI-compatible endpoint

### Reliability

- Failover routing: fall back to alternate models/providers on rate limits or outages
- Automated API key rotation: rotate across multiple keys to reduce throttling and extend free-tier allowances
- Rate limits and context: lightweight rate limiting and per-model context window enforcement

### Safety & Integrity

- Loop detection: detect repeated patterns and halt infinite loops
- Dangerous-command prevention: steer away from destructive shell actions
- Key hygiene: redact API keys in prompts and logs
- Stale token handling: automatic detection and recovery for expired OAuth tokens in backends like Gemini CLI, Anthropic, and OpenAI OAuth
- Brute-force protection: per-IP tracking of invalid API keys with exponential back-off blocking
- Repair helpers: tool-call and JSON repair to fix malformed model outputs

### Control & Ergonomics

- **Model Name Rewrites**: Powerful regex-based model name transformation with configurable rules and precedence
- In-chat switching: change back-end and model on the fly with `!/backend(...)` and `!/model(...)`
- Force model override: static CLI parameter (`--force-model`) to override all client-requested models without modifying client code

### Observability

- Wire capture and audit: optional request/response capture file plus usage tracking
- Trusted IP bypass: optional authentication bypass for specified IP addresses or CIDR ranges (e.g., internal networks)

## Supported APIs (Front-Ends) and Providers (Back-Ends)

These are ready out of the box. Front-ends are the client-facing APIs the proxy exposes; back-ends are the providers the proxy calls.

### Front-ends

| API surface | Path(s) | Typical clients | Notes |
| - | - | - | - |
| OpenAI Chat Completions | `/v1/chat/completions` | Most OpenAI SDKs/tools, coding agents | Default front-end |
| OpenAI Responses | `/v1/responses` | Clients requiring structured JSON output | Provides JSON schema validation and repair |
| Anthropic Messages | `/anthropic/v1/messages` (+ `/anthropic/v1/models`, `/health`, `/info`) | Claude Code, Anthropic SDK | Also available on a dedicated port (see Setup) |
| Google Gemini v1beta | `/v1beta/models`, `:generateContent`, `:streamGenerateContent` | Gemini-compatible tools/SDKs | Translates to your chosen provider |

### Back-ends

| Backend ID | Provider | Authentication | Notes |
| - | - | - | - |
| `openai` | OpenAI | `OPENAI_API_KEY` | Standard OpenAI API |
| `openai-oauth` | OpenAI (ChatGPT/Codex OAuth) | Local `.codex/auth.json` | Uses ChatGPT login token instead of API key |
| `anthropic` | Anthropic | `ANTHROPIC_API_KEY` | Claude models via Messages API |
| `anthropic-oauth` | Anthropic (OAuth) | Local OAuth token | Claude via OAuth credential flow |
| `gemini` | Google Gemini | `GEMINI_API_KEY` | Metered API key |
| `gemini-cli-oauth-personal` | Google Gemini (CLI) | OAuth (no key) | Free-tier personal OAuth like the Gemini CLI |
| `gemini-cli-cloud-project` | Google Gemini (GCP) | OAuth + `GOOGLE_CLOUD_PROJECT` (+ ADC) | Bills to your GCP project |
| `gemini-cli-acp` | Google Gemini (CLI Agent) | OAuth (no key) | Uses gemini-cli as an agent via Agent Control Protocol (ACP) |
| `openrouter` | OpenRouter | `OPENROUTER_API_KEY` | Access to many hosted models |
| `zai` | ZAI | `ZAI_API_KEY` | Zhipu/Z.ai access (OpenAI-compatible) |
| `zai-coding-plan` | ZAI Coding Plan | `ZAI_API_KEY` | Works with any supported front-end and coding agent |
| `qwen-oauth` | Alibaba Qwen | Local `oauth_creds.json` | Qwen CLI OAuth; OpenAI-compatible endpoint |

## Gemini Backends Overview

Choose the Gemini integration that fits your environment.

| Backend | Authentication | Cost | Best for |
| - | - | - | - |
| `gemini` | API key (`GEMINI_API_KEY`) | Metered (pay-per-use) | Production apps, high-volume usage |
| `gemini-cli-oauth-personal` | OAuth (no API key) | Free tier with limits | Local development, testing, personal use |
| `gemini-cli-cloud-project` | OAuth + `GOOGLE_CLOUD_PROJECT` (ADC/service account) | Billed to your GCP project | Enterprise, team workflows, central billing |
| `gemini-cli-acp` | OAuth (no API key) | Free tier with limits | AI agent workflows, project-aware coding tasks |

Notes

- Personal OAuth uses credentials from the local Google CLI/Code Assist-style flow and does not require a `GEMINI_API_KEY`.
- The proxy now validates personal OAuth tokens on startup, watches the `oauth_creds.json` file for changes, and triggers the Gemini CLI in the background when tokens are close to expiring--no manual restarts required.
- Cloud Project requires `GOOGLE_CLOUD_PROJECT` and Application Default Credentials (or a service account file).
- **NEW**: ACP backend uses `gemini-cli` as an agent with full project directory awareness and tool usage capabilities via the Agent Control Protocol.

Quick setup

For `gemini` (API key)

```bash
export GEMINI_API_KEY="AIza..."
python -m src.core.cli --default-backend gemini
```

For `gemini-cli-oauth-personal` (free personal OAuth)

```bash
# Install and authenticate with the Google Gemini CLI (one-time):
gemini auth

# Then start the proxy using the personal OAuth backend
python -m src.core.cli --default-backend gemini-cli-oauth-personal
```

For `gemini-cli-cloud-project` (GCP-billed)

```bash
export GOOGLE_CLOUD_PROJECT="your-project-id"

# Provide Application Default Credentials via one of the following:
# Option A: User credentials (interactive)
gcloud auth application-default login

# Option B: Service account file
export GOOGLE_APPLICATION_CREDENTIALS="/absolute/path/to/service-account.json"

python -m src.core.cli --default-backend gemini-cli-cloud-project
```

For `gemini-cli-acp` (Agent Control Protocol)

```bash
# Install and authenticate with Google Gemini CLI (one-time)
npm install -g @google/gemini-cli
gemini login

# Set project directory (optional - defaults to current directory)
export GEMINI_CLI_WORKSPACE="/path/to/your/project"

# Start the proxy using gemini-cli as an agent
python -m src.core.cli --default-backend gemini-cli-acp

# Change project directory during conversation with slash command
!/project-dir(/path/to/another/project)
```

## Quick Start

1) Export provider keys (only for the back-ends you plan to use)

```bash
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...
export OPENROUTER_API_KEY=...
export ZAI_API_KEY=...
# GCP-based Gemini back-end
export GOOGLE_CLOUD_PROJECT=your-project-id
```

2) Start the proxy

```bash
python -m src.core.cli --default-backend openai
```

Useful flags

- `--host 0.0.0.0` and `--port 8000` to change bind address
- `--config config/config.example.yaml` to load a saved config
- `--capture-file wire.log` to record requests/replies (see Debugging)
- `--disable-auth` for local only (forces host=127.0.0.1)
- `--force-model MODEL_NAME` to override all client-requested models (e.g., `--force-model gemini-2.5-pro`)
- `--force-context-window TOKENS` to override context window size for all models (e.g., `--force-context-window 8000`)
- `--strict-command-detection` to enable strict command detection (only process commands on last non-blank line)
- `--enable-edit-precision` / `--disable-edit-precision` to control automated edit-precision tuning
- `--edit-precision-temperature TEMP` to set target temperature for edit failures (default: 0.1)
- `--edit-precision-min-top-p FLOAT` to set minimum top_p for edit failures (default: 0.3)
- `--edit-precision-override-top-p` to enable top_p override for edit failures
- `--edit-precision-exclude-agents REGEX` to exclude specific agents from edit-precision tuning

3) Point your client at the proxy

- OpenAI-compatible tools: set `OPENAI_API_BASE=http://localhost:8000/v1` and `OPENAI_API_KEY` to your proxy key if auth is enabled
- Claude Code (Anthropic): set `ANTHROPIC_API_URL=http://localhost:8001` and `ANTHROPIC_API_KEY` to your proxy key
- Gemini clients: call the `/v1beta/...` endpoints on `http://localhost:8000`

Tip: Anthropic compatibility is exposed both at `/anthropic/...` on the main port and, if configured, on a dedicated Anthropic port (defaults to main port + 1). Override via `ANTHROPIC_PORT`.

## Using It Day-To-Day

- Switch back-end or model on the fly in the chat input:
  - `!/backend(openai)`
  - `!/model(gpt-4o-mini)`
  - `!/oneoff(openrouter:qwen/qwen3-coder)`
- Adjust reasoning behavior with reasoning alias commands:
  - `!/max`: Activate high reasoning mode (more thoughtful responses)
  - `!/medium`: Activate medium reasoning mode (balanced approach)
  - `!/low`: Activate low reasoning mode (faster, less intensive reasoning)
  - `!/no-think` (or `!/no-thinking`, `!/no-reasoning`, `!/disable-thinking`): Disable reasoning for direct, quick responses

### Strict Command Detection

The proxy supports configurable strict command detection to reduce false positives when commands are mentioned in conversation:

- **Default Mode**: Commands are processed anywhere in the last user message
- **Strict Mode**: Commands are only processed if they appear on the last non-blank line of the message

**Configuration Options** (CLI overrides environment variable and config file):

- **CLI Flag**: `--strict-command-detection` to enable strict mode
- **Environment Variable**: `STRICT_COMMAND_DETECTION=true`
- **Config File**: `strict_command_detection: true`

**Usage Examples**:

```bash
# Enable strict mode via CLI
python -m src.core.cli --strict-command-detection

# Enable via environment variable
export STRICT_COMMAND_DETECTION=true
python -m src.core.cli

# In config.yaml
strict_command_detection: true
```

**Behavior Comparison**:

- Default: `I tried !/help but it didn't work` → Command processed
- Strict: `I tried !/help but it didn't work` → Command ignored (conversation)
- Strict: `Some context\n!/help` → Command processed (last line)

- Keep your existing tools; just point them to the proxy endpoint.
- The proxy handles streaming, retries/failover (if enabled), and output repair.

## Security

- Do not store provider API keys in config files; use environment variables only.
- Common keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `ZAI_API_KEY`, `GOOGLE_CLOUD_PROJECT`.
- Optional proxy auth: set `LLM_INTERACTIVE_PROXY_API_KEY` and require clients to send `Authorization: Bearer <key>`.
- Built-in redaction masks API keys in prompts and logs.

## Debugging (Wire Capture)

The proxy can capture all HTTP traffic between clients and LLM backends for debugging and analysis. Wire capture records the exact requests and responses without logging contamination.

### Quick Start

```bash
# Enable wire capture via CLI
python -m src.core.cli --capture-file logs/wire_capture.log

# Or via configuration
logging:
  capture_file: "logs/wire_capture.log"
```

### Wire Capture Formats

The proxy has evolved through multiple wire capture formats. **Currently active: Buffered JSON Lines format.**

> [!] **Format Compatibility**: Different versions of the proxy use different wire capture formats. Check the format before processing files with external tools.

#### Buffered JSON Lines Format (Current Default)

High-performance format with structured JSON entries, one per line:

```json
{
  "timestamp_iso": "2025-01-10T15:58:41.039145+00:00",
  "timestamp_unix": 1736524721.039145,
  "direction": "outbound_request",
  "source": "127.0.0.1(Cline/1.0)",
  "destination": "qwen-oauth",
  "session_id": "session-123",
  "backend": "qwen-oauth",
  "model": "qwen3-coder-plus",
  "key_name": "primary",
  "content_type": "json",
  "content_length": 1247,
  "payload": {
    "messages": [{"role": "user", "content": "..."}],
    "model": "qwen3-coder-plus",
    "temperature": 0.7
  },
  "metadata": {
    "client_host": "127.0.0.1",
    "user_agent": "Cline/1.0",
    "request_id": "req_abc123"
  }
}
```

**Direction values**: `outbound_request`, `inbound_response`, `stream_start`, `stream_chunk`, `stream_end`

#### Legacy Formats

<details>
<summary>Click to see legacy wire capture formats (for reference)</summary>

**Human-Readable Format** (legacy):

```
----- REQUEST 2025-01-10T15:58:41Z -----
client=127.0.0.1 agent=Cline/1.0 session=session-123 -> backend=qwen-oauth model=qwen3-coder-plus
{
  "messages": [...],
  "model": "qwen3-coder-plus"
}

----- REPLY 2025-01-10T15:58:42Z -----
client=127.0.0.1 agent=Cline/1.0 session=session-123 -> backend=qwen-oauth model=qwen3-coder-plus
{
  "choices": [...]
}
```

**Structured JSON Format** (legacy):

```json
{
  "timestamp": {
    "iso": "2025-01-10T15:58:41.123Z",
    "human_readable": "2025-01-10 15:58:41"
  },
  "communication": {
    "flow": "frontend_to_backend",
    "direction": "request",
    "source": "127.0.0.1",
    "destination": "qwen-oauth"
  },
  "metadata": {
    "session_id": "session-123",
    "backend": "qwen-oauth",
    "model": "qwen3-coder-plus",
    "byte_count": 1247
  },
  "payload": { ... }
}
```

</details>

#### Service Registration

- The active wire capture implementation is `BufferedWireCapture`.
- It is registered via the `CoreServicesStage` as the implementation for `IWireCapture`.
- Legacy DI registration of `StructuredWireCapture` has been removed to prevent format mismatch.
- Initialization is resilient in sync contexts: the background flush task starts lazily when an event loop is available.

### Configuration Options

```yaml
logging:
  capture_file: "logs/wire_capture.log"
  # Performance tuning
  capture_buffer_size: 65536          # 64KB buffer (default)
  capture_flush_interval: 1.0         # Flush every 1 second
  capture_max_entries_per_flush: 100  # Max entries per flush
  # Rotation
  capture_max_bytes: 104857600         # 100MB per file
  capture_max_files: 5                # Keep 5 rotated files
  capture_total_max_bytes: 524288000   # 500MB total cap
```

### Processing Wire Capture Files

```bash
# Count requests by backend
jq -r 'select(.direction=="outbound_request") | .backend' logs/wire_capture.log | sort | uniq -c

# Extract all user messages
jq -r 'select(.direction=="outbound_request") | .payload.messages[]? | select(.role=="user") | .content' logs/wire_capture.log

# Find failed requests (look for error responses)
jq 'select(.direction=="inbound_response" and (.payload.error or .payload.choices == null))' logs/wire_capture.log

# Calculate token usage by model
jq -r 'select(.direction=="inbound_response" and .payload.usage) | "\(.model) \(.payload.usage.total_tokens // (.payload.usage.prompt_tokens + .payload.usage.completion_tokens))"' logs/wire_capture.log
```

### Security Notes

- Wire capture respects prompt redaction settings - API keys in prompts are masked
- The `key_name` field shows which environment variable was used, not the actual key
- Capture files may contain sensitive conversation data - secure appropriately
- Consider using `capture_total_max_bytes` to prevent unbounded disk usage

### Authentication & Brute-Force Protection

API key authentication is enabled by default. Each client IP is allowed a limited
number of invalid API key attempts before the proxy responds early with a `429`
status and a progressively increasing `Retry-After` delay. Successful
authentications reset the counter immediately.

**Default behaviour**

- 5 invalid attempts per IP are allowed within a 15-minute window.
- The first block lasts 30 seconds and doubles on each repeated failure up to a
  one-hour cap.
- Trusted IPs and endpoints in the bypass list (`/docs`, `/openapi.json`,
  `/redoc`) skip brute-force checks entirely.

**Configuration options** (CLI > Environment > YAML):

- CLI flags:
  - `--enable-brute-force-protection` / `--disable-brute-force-protection`
  - `--auth-max-failed-attempts <int>`
  - `--auth-brute-force-ttl <seconds>`
  - `--auth-brute-force-initial-block <seconds>`
  - `--auth-brute-force-multiplier <float>`
  - `--auth-brute-force-max-block <seconds>`
- Environment variables:
  - `BRUTE_FORCE_PROTECTION_ENABLED`
  - `BRUTE_FORCE_MAX_FAILED_ATTEMPTS`
  - `BRUTE_FORCE_TTL_SECONDS`
  - `BRUTE_FORCE_INITIAL_BLOCK_SECONDS`
  - `BRUTE_FORCE_BLOCK_MULTIPLIER`
  - `BRUTE_FORCE_MAX_BLOCK_SECONDS`
- `config.yaml` snippet:

  ```yaml
  auth:
    brute_force_protection:
      enabled: true
      max_failed_attempts: 5
      ttl_seconds: 900
      initial_block_seconds: 30
      block_multiplier: 2.0
      max_block_seconds: 3600
  ```

### Advanced Wire Capture Documentation

For detailed information about wire capture formats, migration between versions, and processing examples, see [docs/wire_capture_formats.md](docs/wire_capture_formats.md).

## Model Name Rewrites

The Model Name Rewrites feature provides a powerful, rule-based system for dynamically transforming model names before they are processed by the proxy. This enables seamless model routing, backend abstraction, and fallback strategies without requiring changes to client applications.

### Key Benefits

- **Backend Abstraction**: Hide specific backend details from client applications
- **Seamless Migration**: Switch underlying models without updating client code
- **Cost Optimization**: Route expensive models to cheaper alternatives
- **Fallback Strategies**: Create catch-all rules for unrecognized models
- **Provider Consolidation**: Route all requests of a certain type through a preferred provider

### Configuration Sources

Model aliases can be configured through three sources with the following precedence order:

**1. CLI Parameters (Highest Precedence)**
```bash
# Single alias
--model-alias "^gpt-(.*)=openrouter:openai/gpt-\1"

# Multiple aliases
--model-alias "^gpt-(.*)=openrouter:openai/gpt-\1" \
--model-alias "^claude-(.*)=anthropic:claude-\1" \
--model-alias "^(.*)=gemini-cli-oauth-personal:gemini-1.5-pro"
```

**2. Environment Variables (Medium Precedence)**
```bash
export MODEL_ALIASES='[
  {"pattern": "^gpt-(.*)", "replacement": "openrouter:openai/gpt-\\1"},
  {"pattern": "^claude-(.*)", "replacement": "anthropic:claude-\\1"},
  {"pattern": "^(.*)$", "replacement": "gemini-cli-oauth-personal:gemini-1.5-pro"}
]'
```

**3. Config File (Lowest Precedence)**
```yaml
model_aliases:
  # Static replacement for specific model
  - pattern: "^claude-3-sonnet-20240229$"
    replacement: "gemini-cli-oauth-personal:gemini-1.5-flash"
  
  # Dynamic replacement with capture groups
  - pattern: "^gpt-(.*)"
    replacement: "openrouter:openai/gpt-\\1"
  
  # Catch-all fallback for any other model
  - pattern: "^(.*)$"
    replacement: "gemini-cli-oauth-personal:gemini-1.5-pro"
```

### Rule Processing

- **First Match Wins**: Rules are processed in order, and the first matching pattern is applied
- **Regex Support**: Patterns use Python regular expressions with full capture group support
- **Validation**: Invalid regex patterns are caught early with helpful error messages
- **Precedence**: CLI parameters override environment variables, which override config file settings

### Common Use Cases

**Route All GPT Models to OpenRouter:**
```yaml
model_aliases:
  - pattern: "^gpt-(.*)"
    replacement: "openrouter:openai/gpt-\\1"
```

**Replace Expensive Models with Cheaper Alternatives:**
```yaml
model_aliases:
  - pattern: "^gpt-4o$"
    replacement: "gemini-cli-oauth-personal:gemini-1.5-pro"
  - pattern: "^claude-3-opus.*"
    replacement: "anthropic:claude-3-sonnet-20240229"
```

**Create Environment-Specific Routing:**
```bash
# Development environment - use free models
export MODEL_ALIASES='[
  {"pattern": "^.*$", "replacement": "gemini-cli-oauth-personal:gemini-1.5-flash"}
]'

# Production environment - use premium models
export MODEL_ALIASES='[
  {"pattern": "^gpt-(.*)", "replacement": "openai:gpt-\\1"},
  {"pattern": "^claude-(.*)", "replacement": "anthropic:claude-\\1"}
]'
```

**Override for Specific Applications:**
```bash
# Force a specific application to use your preferred model
./my-app | llm-proxy --model-alias ".*=my-backend:my-preferred-model"
```

### Integration with Other Features

Model aliases work seamlessly with other proxy features:

- **Static Route**: `--static-route` takes precedence over model aliases
- **Planning Phase**: Operates on the rewritten model names
- **Failover**: Failover routes use the final rewritten model names
- **In-Chat Commands**: `!/model(...)` commands respect alias rules

### Error Handling

The proxy provides robust error handling for model aliases:

- **Invalid Regex**: Patterns are validated at startup/parse time
- **Malformed JSON**: Environment variable errors are logged as warnings
- **Schema Validation**: Config file validation ensures proper structure
- **Graceful Fallback**: Invalid rules are skipped, processing continues

## Optional Capabilities (Short List)

### Pytest Output Compression
### Planning-Phase Strong Model Overrides

Use a more capable "strong" model for the early planning phase of a session, then switch back to your default model once execution starts. This helps ensure high-quality initial analysis and planning without paying strong-model costs for the whole session.

- **Why useful**:
  - **Better initial planning**: Early prompts often set the trajectory of an entire session. Stronger reasoning models can plan tasks more effectively.
  - **Cost and speed control**: After planning, the system returns to your normal/default model to control costs and improve turnaround.
  - **Minimal configuration**: No arbiter; switching is automatic based on simple counters (turns or file writes).

- **Behavior**:
  - If enabled, the proxy routes early requests to a configured strong model unless the current model is already the strong model.
  - Switching back happens when either:
    - The maximum number of planning turns is reached; or
    - The model performs a file-writing tool call (e.g., write/edit/apply_diff/patch).
  - File-tool detection is handled by the existing Tool Call Reactor for reliability.

- **Configuration (precedence: CLI > Env > YAML)**:
  - YAML (`config.yaml`):
    ```yaml
    session:
      planning_phase:
        enabled: true
        strong_model: "openai:gpt-4o"
        max_turns: 10
        max_file_writes: 1
        overrides:
          temperature: 0.2
          top_p: 0.9
          reasoning_effort: "high"
          thinking_budget: 8000
    ```
  - Environment variables:
    - `PLANNING_PHASE_ENABLED=true|false`
    - `PLANNING_PHASE_STRONG_MODEL=backend:model` (e.g., `openai:gpt-4o`)
    - `PLANNING_PHASE_MAX_TURNS=10`
    - `PLANNING_PHASE_MAX_FILE_WRITES=1`
    - `PLANNING_PHASE_TEMPERATURE=0.2`
    - `PLANNING_PHASE_TOP_P=0.9`
    - `PLANNING_PHASE_REASONING_EFFORT=high`
    - `PLANNING_PHASE_THINKING_BUDGET=8000`
  - CLI flags:
    - `--enable-planning-phase`
    - `--planning-phase-strong-model BACKEND:MODEL`
    - `--planning-phase-max-turns N`
    - `--planning-phase-max-file-writes N`
    - `--planning-phase-temperature FLOAT`
    - `--planning-phase-top-p FLOAT`
    - `--planning-phase-reasoning-effort EFFORT`
    - `--planning-phase-thinking-budget TOKENS`

- **Usage example**:
  ```bash
  python -m src.core.cli \
    --default-backend openai \
    --enable-planning-phase \
    --planning-phase-strong-model openai:gpt-4o \
    --planning-phase-max-turns 8 \
    --planning-phase-max-file-writes 1 \
    --planning-phase-temperature 0.2 \
    --planning-phase-top-p 0.9 \
    --planning-phase-reasoning-effort high \
    --planning-phase-thinking-budget 8000
  ```

Notes:
- If the current model already equals the strong model, no override is applied.
- After switching back, requests use whatever the normal routing would select.
- File-write detection reuses the Tool Call Reactor; no duplicate detection logic.


### Planning-Phase Strong Model Overrides

Use a more capable "strong" model for the early planning phase of a session, then switch back to your default model once execution starts. This helps ensure high-quality initial analysis and planning without paying strong-model costs for the whole session.

- **Why useful**:
  - **Better initial planning**: Early prompts often set the trajectory of an entire session. Stronger reasoning models can plan tasks more effectively.
  - **Cost and speed control**: After planning, the system returns to your normal/default model to control costs and improve turnaround.
  - **Minimal configuration**: No arbiter; switching is automatic based on simple counters (turns or file writes).

- **Behavior**:
  - If enabled, the proxy routes early requests to a configured strong model unless the current model is already the strong model.
  - Switching back happens when either:
    - The maximum number of planning turns is reached; or
    - The model performs a file-writing tool call (e.g., write/edit/apply_diff/patch).
  - File-tool detection is handled by the existing Tool Call Reactor for reliability.

- **Configuration (precedence: CLI > Env > YAML)**:
  - YAML (`config.yaml`):

    ```yaml
    session:
      planning_phase:
        enabled: true
        strong_model: "openai:gpt-4o"
        max_turns: 10
        max_file_writes: 1
        overrides:
          temperature: 0.2
          top_p: 0.9
          reasoning_effort: "high"
          thinking_budget: 8000
    ```

  - Environment variables:
    - `PLANNING_PHASE_ENABLED=true|false`
    - `PLANNING_PHASE_STRONG_MODEL=backend:model` (e.g., `openai:gpt-4o`)
    - `PLANNING_PHASE_MAX_TURNS=10`
    - `PLANNING_PHASE_MAX_FILE_WRITES=1`
    - `PLANNING_PHASE_TEMPERATURE=0.2`
    - `PLANNING_PHASE_TOP_P=0.9`
    - `PLANNING_PHASE_REASONING_EFFORT=high`
    - `PLANNING_PHASE_THINKING_BUDGET=8000`
  - CLI flags:
    - `--enable-planning-phase`
    - `--planning-phase-strong-model BACKEND:MODEL`
    - `--planning-phase-max-turns N`
    - `--planning-phase-max-file-writes N`
    - `--planning-phase-temperature FLOAT`
    - `--planning-phase-top-p FLOAT`
    - `--planning-phase-reasoning-effort EFFORT`
    - `--planning-phase-thinking-budget TOKENS`

- **Usage example**:

  ```bash
  python -m src.core.cli \
    --default-backend openai \
    --enable-planning-phase \
    --planning-phase-strong-model openai:gpt-4o \
    --planning-phase-max-turns 8 \
    --planning-phase-max-file-writes 1 \
    --planning-phase-temperature 0.2 \
    --planning-phase-top-p 0.9 \
    --planning-phase-reasoning-effort high \
    --planning-phase-thinking-budget 8000
  ```

Notes:

- If the current model already equals the strong model, no override is applied.
- After switching back, requests use whatever the normal routing would select.
- File-write detection reuses the Tool Call Reactor; no duplicate detection logic.

The proxy automatically compresses verbose pytest output to preserve context window space while maintaining error information:

- **Automatic Detection**: Recognizes pytest commands (`pytest`, `python -m pytest`, `py.test`, etc.)
- **Smart Filtering**: Removes verbose timing info (`s setup`, `s call`, `s teardown`) and `PASSED` test results
- **Error Preservation**: Keeps `FAILED` tests and error messages intact
- **Configurable**: Can be enabled/disabled globally or per-session
- **Compression Stats**: Logs compression ratios for monitoring

**Configuration Options:**

The feature can be controlled via CLI flags, environment variables, or the `config.yaml` file. The order of precedence is: CLI > Environment Variable > `config.yaml`.

- **CLI Flags**:
  - `--enable-pytest-compression`: Explicitly enables compression for the current session.
  - `--disable-pytest-compression`: Explicitly disables compression for the current session.

- **Environment Variable**:

  ```bash
  export PYTEST_COMPRESSION_ENABLED=true # or false
  ```

- **`config.yaml`**:

  ```yaml
  session:
    pytest_compression_enabled: true  # Default: true
  ```

**Example Output Transformation:**

```
# Before compression (verbose):
test_example.py::test_function PASSED                    [ 50%] 0.001s setup 0.002s call 0.001s teardown
test_example.py::test_failure FAILED                     [100%] 0.001s setup 0.003s call 0.001s teardown

# After compression (concise):
test_example.py::test_failure FAILED                     [100%]
```

📖 **[Full Documentation](docs/pytest-compression.md)** - Detailed configuration options, use cases, and troubleshooting

### Context Window Enforcement

The proxy enforces per-model context window limits at the front-end, preventing requests that exceed model capabilities and providing clear error messages before they reach backend providers.

- **Customizable Limits**: Configure different context window sizes per model and backend
- **Input Token Enforcement**: Blocks requests that exceed input token limits with structured error responses
- **Front-end Protection**: Prevents unnecessary API calls and costs by validating limits before backend requests
- **Flexible Configuration**: Supports both `context_window` and `max_input_tokens` for fine-grained control

**Configuration Options:**

Context windows are configured in backend-specific YAML files or model defaults:

```yaml
# Backend-specific configuration (e.g., config/backends/custom/backend.yaml)
models:
  "your-model-name":
    limits:
      context_window: 262144        # Total context window size (tokens)
      max_input_tokens: 200000      # Input token limit (tokens)
      max_output_tokens: 62144      # Output token limit (tokens)
      requests_per_minute: 60       # Rate limits
      tokens_per_minute: 1000000

# Or in main config via model_defaults
model_defaults:
  "your-model-name":
    limits:
      context_window: 128000        # 128K context window
      max_input_tokens: 100000      # 100K input limit
```

**Error Handling:**

When limits are exceeded, the proxy returns a structured 400 error:

```json
{
  "detail": {
    "code": "input_limit_exceeded",
    "message": "Input token limit exceeded",
    "details": {
      "model": "your-model-name",
      "limit": 100000,
      "measured": 125432
    }
  }
}
```

**Implementation Notes:**

- Input limits are enforced strictly; output limits are handled by backend providers
- `context_window` acts as a fallback when `max_input_tokens` is not specified
- Token counting uses model-specific tokenizers when available
- Configuration supports both `backend:model` and plain `model` key formats

### Other Capabilities

- Failover and retries: route requests to a next-best model when one fails
- JSON repair: fix common JSON formatting issues (streaming and non-streaming)
- Tool-call repair: convert textual tool calls to proper `tool_calls`
- Tool Call Reactor: event-driven system to intercept and steer tool calls (e.g., apply_diff to patch_file), with configurable YAML rules and rate limiting
- Opt-in pytest full-suite steering: warns before running the entire pytest suite and requires a second confirmation
- Loop detection: stop repeated identical tool calls
- Dangerous-command prevention: steer away from destructive shell actions
- Empty response recovery: automatic retry with steering prompt on empty LLM responses
- Identity header override: control X-Title/Referer/User-Agent per back-end
- Content rewriting: REPLACE/PREPEND/APPEND rules on inbound/outbound content
- Context window enforcement: per-model token limits with configurable context window sizes and friendly errors

**Advanced Configs (YAML)**:

- `config/reasoning_aliases.yaml`: Per-model reasoning modes (e.g., temperature, max tokens, prompt prefixes)
- `config/edit_precision_patterns.yaml`: Patterns for auto-tuning on edit failures
- `config/tool_call_reactor_config.yaml`: Rules for tool call reactions and steering

## Example Config (minimal)

```yaml
# config.yaml
backends:
  openai:
    type: openai
default_backend: openai
proxy:
  host: 0.0.0.0
  port: 8000
auth:
  # Set LLM_INTERACTIVE_PROXY_API_KEY env var to enable
  disable_auth: false
```

Run: `python -m src.core.cli --config config.yaml`

## Popular Scenarios

### Claude Code with any model/provider

1) Start the proxy with your preferred back-end (e.g., OpenAI or OpenRouter)
2) Ensure Anthropic front-end is reachable (main port `/anthropic/...` or `ANTHROPIC_PORT`)
3) Set

```bash
export ANTHROPIC_API_URL=http://localhost:8001
export ANTHROPIC_API_KEY=<your-proxy-key>
```

Then launch `claude`. You can switch models during a session:

```
!/backend(openrouter)
!/model(claude-3-5-sonnet-20241022)
```

### Z.AI Coding Plan with coding agents

- Use back-end `zai-coding-plan`; it works with any supported front-end and any coding agent
- Point OpenAI-compatible tools at `http://localhost:8000/v1`

### Gemini options

- Metered API key (`gemini`), free personal OAuth (`gemini-cli-oauth-personal`), GCP-billed (`gemini-cli-cloud-project`), or agent mode (`gemini-cli-acp`). Pick one and set the required env vars.

### Gemini CLI Agent with ACP

Use `gemini-cli` as an AI agent with full project directory awareness:

```bash
# Install gemini-cli (one-time)
npm install -g @google/gemini-cli
gemini login

# Start proxy with agent backend
python -m src.core.cli --default-backend gemini-cli-acp

# Project directory control options (in priority order):
# 1. Runtime slash command (highest priority)
!/project-dir(/home/user/myproject)

# 2. Config file (config/backends/gemini-cli-acp/backend.yaml)
project_dir: "/path/to/your/project"

# 3. Environment variable
export GEMINI_CLI_WORKSPACE="/path/to/project"

# 4. Current working directory (fallback)
```

**Features:**

- Full project directory awareness - gemini-cli can read, analyze, and modify files
- Tool usage - agent can execute commands and use tools
- Dynamic directory switching - change project directory during conversation with `!/project-dir(path)`
- Streaming responses - real-time output from the agent
- Auto-accept mode - automatically approve safe operations (configurable)

### Force a specific model across all requests

Use `--force-model` to override whatever model the client requests, useful for:

- Testing a specific model with any client/agent without modifying client code
- Enforcing a particular model across different sessions
- Routing free-tier OAuth backends (e.g., `gemini-cli-oauth-personal`) to specific models

Example:

```bash
python -m src.core.cli \
  --default-backend gemini-cli-oauth-personal \
  --force-model gemini-2.5-pro \
  --disable-auth \
  --port 8000
```

Now any client requesting `gpt-4`, `claude-3-opus`, or any other model will actually use `gemini-2.5-pro` on the gemini-cli-oauth-personal backend.

### Override context window size for all models

Use `--force-context-window` to set a static context window size that overrides all model-specific configurations, useful for:

- **Testing compatibility**: Verify how agents behave with smaller context windows
- **Cost control**: Limit token usage regardless of model capabilities
- **Performance optimization**: Reduce context size for faster responses
- **Debugging**: Test with fixed context windows to isolate issues

Example:

```bash
python -m src.core.cli \
  --default-backend openai \
  --force-context-window 8000 \
  --disable-auth \
  --port 8000
```

This sets an 8K token context window limit for **all models**, regardless of their individual configurations (even if models support 128K or 256K contexts).

**Common use cases:**

```bash
# Simulate smaller model context limits for testing
python -m src.core.cli --force-context-window 4096

# Strict cost control with conservative limits
python -m src.core.cli --force-context-window 2000

# Balance between capability and performance
python -m src.core.cli --force-context-window 16000
```

### Edit-Precision Tuning Examples

Control automated model parameter tuning when file edits fail:

```bash
# Enable edit-precision tuning with default settings
python -m src.core.cli --enable-edit-precision

# Disable edit-precision tuning entirely
python -m src.core.cli --disable-edit-precision

# Custom temperature for precision (lower = more deterministic)
python -m src.core.cli --edit-precision-temperature 0.05

# Custom top_p value and enable override
python -m src.core.cli --edit-precision-min-top-p 0.2 --edit-precision-override-top-p

# Exclude specific agents from edit-precision (e.g., exclude "test" agents)
python -m src.core.cli --edit-precision-exclude-agents "test.*"

# Combine multiple edit-precision settings
python -m src.core.cli \
  --enable-edit-precision \
  --edit-precision-temperature 0.08 \
  --edit-precision-min-top-p 0.25 \
  --edit-precision-override-top-p
```

### Configure custom context window limits

Protect against excessive token usage and cost overruns by configuring per-model context window limits:

```yaml
# config/backends/custom-models/backend.yaml
backend_type: "custom"
models:
  "large-context-model":
    limits:
      context_window: 262144      # 256K total context window
      max_input_tokens: 200000    # 200K input limit (leaves room for response)
      requests_per_minute: 30     # Conservative rate limits
  "small-fast-model":
    limits:
      context_window: 8192        # 8K context window
      max_input_tokens: 6000      # 6K input limit
      requests_per_minute: 120    # Higher rate for smaller model
```

**Use cases:**

- **Cost Control**: Prevent accidental large-context requests with expensive models
- **Agent Compatibility**: Ensure agents with long conversations don't exceed model limits
- **Performance Tuning**: Optimize different models for different use cases
- **Multi-tier Service**: Configure different limits for different user tiers or applications

## Errors and Troubleshooting

- 401/403 from proxy: missing/invalid `Authorization` header when proxy auth is enabled
- 400 Bad Request: malformed payload; ensure you send an OpenAI/Anthropic/Gemini-compatible body
- 422 Unprocessable Entity: validation error; check error details for the field
- 400 with `input_limit_exceeded`: request exceeds model's context window limits - check error details for measured vs limit tokens
- 503 Service Unavailable: upstream provider is unreachable; try another model or enable failover
- Model not found: ensure the model name exists for the selected back-end

## Tips

- Enable wire capture for tricky issues: `--capture-file wire.jsonl`
- Use in-chat `!/backend(...)` and `!/model(...)` to isolate provider/model problems
- Check environment variables are set for the back-end you selected

## Running Tests

The pytest configuration in [`pyproject.toml`](pyproject.toml) enables async and parallel execution via `--asyncio-mode=auto` and `-n`. Those flags rely on plugins (`pytest-asyncio`, `pytest-xdist`) that are declared in the `dev` optional dependency group, so they are not installed by a plain `pip install -e .`. Install the development extras before running the suite:

```bash
python -m pip install -e .[dev]
python -m pytest
```

The commands above work on Linux, macOS, and Windows as long as they are executed from the virtual environment you created for the project (for example `.venv/bin/python` on Unix-like systems or `.venv\Scripts\python.exe` on Windows).

## Support

- Issues: open a ticket in the repository's issue tracker

## License

This project is licensed under the AGPL-3.0-or-later (GNU Affero General Public License v3.0 or later) -- see the [LICENSE](LICENSE) file for details.

## Changelog

See the full change history in [CHANGELOG.md](CHANGELOG.md)
