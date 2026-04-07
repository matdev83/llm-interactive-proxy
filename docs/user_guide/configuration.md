# Configuration Guide

The LLM Interactive Proxy supports multiple configuration methods with a clear precedence order. This guide explains how to configure the proxy using CLI arguments, environment variables, and YAML configuration files.

## Configuration Precedence

Configuration values are resolved in the following order (highest to lowest priority):

1. **CLI Arguments** - Command-line flags (highest priority)
2. **Environment Variables** - Shell environment variables
3. **YAML Configuration File** - Configuration file specified with `--config`
4. **Default Values** - Built-in defaults (lowest priority)

When the same setting is specified in multiple places, the higher priority source wins.

## Configuration Methods

### 1. CLI Arguments

Command-line arguments provide the highest priority configuration and are ideal for:

- Quick testing and experimentation
- Overriding specific settings temporarily
- Scripting and automation

**Example**:

```bash
python -m src.core.cli \
  --default-backend openai \
  --host 127.0.0.1 \
  --port 8000 \
  --enable-edit-precision \
  --disable-auth
```

See the [CLI Parameters Reference](cli-parameters.md) for a complete list of all available CLI flags and their corresponding environment variables.

### 2. Environment Variables

Environment variables are useful for:

- Storing sensitive information (API keys)
- Setting defaults for your development environment
- CI/CD pipelines and deployment scripts

**Common Environment Variables**:

```bash
# API Keys
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GEMINI_API_KEY=...
export OPENROUTER_API_KEY=sk-or-...

# Backend Selection
export LLM_BACKEND=openai
export STATIC_ROUTE="gemini-oauth-plan:gemini-2.5-pro"
export DISABLE_GEMINI_OAUTH_REASONING_PROMPT_INJECTION=false

# Proxy Configuration
export APP_HOST=127.0.0.1
export APP_PORT=8000
export PROXY_TIMEOUT=120

# Auth
export DISABLE_AUTH=false
export AUTH_TOKEN=your-secret-token

# Feature Toggles
export DANGEROUS_COMMAND_PREVENTION_ENABLED=true
export EDIT_PRECISION_ENABLED=true
export ENABLE_SANDBOXING=true
export PLANNING_PHASE_ENABLED=true
```

### 3. YAML Configuration Files

YAML configuration files are best for:

- Persistent configuration across sessions
- Complex multi-backend setups
- Team-shared configurations
- Documenting your setup

**Run with config file**:

```bash
python -m src.core.cli --config config.yaml
```

## Complete Configuration Reference

The following YAML structure represents the full configuration schema.

### Root Settings

```yaml
host: "127.0.0.1"              # Bind host
port: 8000                     # Bind port
anthropic_port: 8001           # Optional: second listener for root /v1/messages (omit/null to disable)
proxy_timeout: 120             # Global request timeout (seconds)
command_prefix: "!/"           # Command prefix for in-chat commands
strict_command_detection: false # Require commands to be at start of message
context_window_override: null  # Override context window size (int)
disable_health_checks: false   # Disable /health endpoint (not the health monitoring system)
gcp_project_id: null           # Google Cloud Project ID
gemini_credentials_path: null  # Path to Gemini credentials JSON

# Model Registry & Limit Enforcement
model_registry:
  download_enabled: true        # Download model metadata updates
  url: "https://models.dev/api.json"
  update_interval_seconds: 86400
  cache_path: "./var/model_registry/models.dev.json"
  bootstrap_path: "./src/resources/model_registry/models.dev.json"

model_limit_enforcement:
  enabled: true                 # Enforce context window + modality checks when metadata exists
```

### Backend Settings (`backends`)

```yaml
backends:
  default_backend: "openai"    # Default backend identifier
  static_route: null           # Force all traffic to "backend:model"
  disable_gemini_oauth_fallback: false
  disable_gemini_oauth_reasoning_prompt_injection: false
  disable_hybrid_backend: false
  hybrid_backend_repeat_messages: false
  reasoning_injection_probability: 1.0
  hybrid_reasoning_model_timeout: 60
  hybrid_reasoning_force_initial_turns: 1
  hybrid_execution_model_timeout: 120
  
  # Backend-specific configurations
  openai:
    api_key: "sk-..."          # API key string (or None)
    api_url: "https://api.openai.com/v1"
    timeout: 120
    models: []                 # Optional list of supported models
    
  anthropic:
    api_key: "sk-ant-..."
    api_url: "https://api.anthropic.com/v1"
    
  gemini:
    api_key: "..."
    api_url: "https://generativelanguage.googleapis.com"
    extra:
      strip_reasoning_content: true     # Remove assistant reasoning_content (default: true)
      tool_output_truncate_chars: null  # Optional tool output truncation (disabled by default)
      tool_output_truncate_lines: null  # Optional tool output truncation (disabled by default)
      tool_output_truncation_log_level: null  # "DEBUG", "INFO", or "off" (default: null)

  gemini-oauth-auto:
    selection_strategy: "session-affinity"  # session-affinity, round-robin, random, first-available
    session_affinity_ttl_seconds: 86400   # Only used with session-affinity
    session_affinity_max_entries: 10000   # Only used with session-affinity
    refresh_buffer_seconds: 300
    extra:
      strip_reasoning_content: true     # Remove assistant reasoning_content (default: true)
      tool_output_truncate_chars: null  # Optional tool output truncation (disabled by default)
      tool_output_truncate_lines: null  # Optional tool output truncation (disabled by default)
      tool_output_truncation_log_level: null  # "DEBUG", "INFO", or "off" (default: null)
    
  openrouter:
    api_key: "sk-or-..."
    api_url: "https://openrouter.ai/api/v1"

  minimax:
    api_key: "..."
    api_url: "https://api.minimax.io/v1"
    
  # Custom/Other backends follow the same structure
```

Gemini-specific `extra` options support request adjustments like stripping `reasoning_content` and optional tool
output truncation. Tool output truncation is automatically skipped when history compaction is enabled to avoid
double reduction. Environment overrides: `GEMINI_STRIP_REASONING_CONTENT`,
`GEMINI_TOOL_OUTPUT_TRUNCATE_CHARS`, `GEMINI_TOOL_OUTPUT_TRUNCATE_LINES`,
`GEMINI_TOOL_OUTPUT_TRUNCATION_LOG_LEVEL`.

### Authentication (`auth`)

```yaml
auth:
  disable_auth: false          # Disable authentication (forces localhost)
  auth_token: "secret-token"   # Shared secret token
  api_keys: []                 # List of allowed client API keys
  redact_api_keys_in_prompts: true
  trusted_ips: []              # List of trusted IP addresses
  
  brute_force_protection:
    enabled: true
    max_failed_attempts: 5
    ttl_seconds: 900
    initial_block_seconds: 30
    block_multiplier: 2.0
    max_block_seconds: 3600
```

### Session Management (`session`)

```yaml
session:
  cleanup_enabled: true
  cleanup_interval: 3600       # Seconds
  max_age: 86400               # Seconds (24 hours)
  default_interactive_mode: true
  force_set_project: false     # Require project name
  disable_interactive_commands: false
  project_dir_resolution_model: null
  project_dir_resolution_mode: "hybrid" # deterministic, llm, hybrid
  
  # File Access Sandboxing
  sandboxing:
    enabled: false
    strict_mode: false
    allow_parent_access: false

  # Safety & Steering
  dangerous_command_prevention_enabled: true
  dangerous_command_steering_message: null
  force_reprocess_tool_calls: false
  log_skipped_tool_calls: false
  
  # Tool Call Repair
  tool_call_repair_enabled: true
  tool_call_repair_buffer_cap_bytes: 65536
  
  # JSON Repair
  json_repair_enabled: true
  json_repair_buffer_cap_bytes: 65536
  json_repair_strict_mode: false
  json_repair_schema: null     # Optional JSON schema
  
  # Pytest Integration
  pytest_compression_enabled: true
  pytest_compression_min_lines: 30
  pytest_full_suite_steering_enabled: false
  pytest_full_suite_steering_message: null
  pytest_context_saving_enabled: false
  test_execution_reminder_enabled: false
  test_execution_reminder_message: null
  
  # Fixes
  fix_think_tags_enabled: false
  fix_think_tags_streaming_buffer_size: 4096
  
  # Quality Verifier
  quality_verifier_model: null            # "backend:model"
  quality_verifier_frequency: 10          # Every N eligible turns (main-model turns)
  quality_verifier_max_history: null      # Optional history truncation (int)
  
  # Planning Phase
  planning_phase:
    enabled: false
    strong_model: null         # "backend:model"
    max_turns: 10
    max_file_writes: 1
    overrides:                 # Optional overrides for strong model
      temperature: 0.7
      top_p: 0.9
      
  # Session Continuity
  session_continuity:
    enabled: true
    fuzzy_matching: true
    max_session_age_seconds: 604800
    fingerprint_message_count: 5
    client_key_includes_ip: true
    
  # Streaming Sampler (Observability)
  streaming_sampler:
    enabled: true
    sample_rate: 0.01          # 1% sampling
    max_samples: 100
    
  # Tool Call Reactor & Access Control
  tool_call_reactor:
    enabled: true
    
    # Legacy Apply Diff Steering
    apply_diff_steering_enabled: true
    apply_diff_steering_rate_limit_seconds: 60
    apply_diff_steering_message: null
    
    access_policies:           # List of access policies
      - name: "block-dangerous"
        model_pattern: ".*"
        default_policy: "allow"
        blocked_patterns: ["delete_.*", "rm_.*"]
```

### Logging & Capture (`logging`)

```yaml
logging:
  level: "INFO"                # DEBUG, INFO, WARNING, ERROR, CRITICAL
  request_logging: false       # Log full request bodies
  response_logging: false      # Log full response bodies
  log_file: "./var/logs/proxy.log"
  
  # Wire Capture (JSON)
  capture_file: null           # Path to capture file
  capture_max_bytes: null      # Rotation threshold
  capture_truncate_bytes: null # Truncate payloads
  capture_max_files: null      # Max rotated files
  capture_rotate_interval_seconds: 86400
  capture_total_max_bytes: 104857600
  capture_buffer_size: 65536
  capture_flush_interval: 1.0
  capture_max_entries_per_flush: 100
  
  # Wire Capture (CBOR)
  cbor_capture_dir: null       # Directory for CBOR captures
  cbor_capture_session_id: null
```

### Virtual Tool Calling (`vtc_client_patterns`)

Configure detection of clients that use Virtual Tool Calling (XML-based tool calls in message content). See [VTC Architecture](../development_guide/vtc-architecture.md) for details.

```yaml
# VTC client detection patterns (case-insensitive substring matching on User-Agent)
vtc_client_patterns:
  - cline       # Cline VSCode extension
  - kilo        # KiloCode
  - roo         # RooCode
  # - myclient  # Add your custom VTC client patterns
```

To disable VTC detection entirely:

```yaml
vtc_client_patterns: []
```

### Edit Precision Tuning (`edit_precision`)

```yaml
edit_precision:
  enabled: true
  temperature: 0.1
  min_top_p: 0.3
  override_top_p: false
  override_top_k: false
  target_top_k: null
  exclude_agents_regex: null
```


```yaml
  enabled: false
  backend: "openai"
  model: "gpt-4o-mini"
  turn_threshold: 30
  confidence_threshold: 0.9
  history_window: 20

### Random Model Replacement (`replacement`)

See [Random Model Replacement Feature Guide](features/random-model-replacement.md) for detailed documentation.

```yaml
replacement:
  enabled: false
  probability: 0.0             # 0.0 to 1.0
  backend_model: null          # "backend:model"
  turn_count: 1                # Number of turns to stay on replacement
  allow_oauth_auto_replacement: false # Allow replacement for oauth-auto
```

```

### Client Identity (`identity`)

```yaml
identity:
  title:
    mode: "passthrough"        # passthrough, override, default
    override_value: null
    default_value: "llm-interactive-proxy"
  url:
    mode: "passthrough"
    override_value: null
    default_value: "https://github.com/matdev83/llm-interactive-proxy"
  user_agent:
    mode: "passthrough"
    override_value: null
    default_value: "llm-interactive-proxy"
```

### Codebuff Server (`codebuff`)

```yaml
codebuff:
  enabled: false
  websocket_path: "/ws"
  heartbeat_timeout_seconds: 60
  session_cleanup_hours: 1
  max_connections: 1000
  max_message_size_bytes: 1048576
```

### Model Defaults & Routing

```yaml
# Default parameters for specific models
model_defaults:
  "gpt-4":
    temperature: 0.7
    max_tokens: 8192

# Failover configuration
failover_routes:
  "primary-model-id":
    policy: "round-robin"
    elements: ["backup-model-1", "backup-model-2"]

# Routing Control
routing:
  disable_backend_ids: false        # Disable routing via explicit backend IDs (e.g. openai.1:gpt-4)
  disable_backend_names: false      # Disable routing via backend names (e.g. openai:gpt-4)
  disable_model_names: false        # Disable routing via model name only (e.g. gpt-4)

# Auxiliary Request Routing
# Routes auxiliary requests (title/summary generation) to alternative backends
# to reduce rate limiting pressure on the primary backend.
#
# Automatic Enable (Single User Mode): Auxiliary routing is automatically enabled
# when OPENROUTER_API_KEY is set, server runs in Single User Mode (default),
# and disable is not set to true. When auto-enabled with no explicit model,
# defaults to "openrouter:openrouter/free".
#
# disable_default_openrouter: true prevents the default model from being set
# to "openrouter:openrouter/free" when OPENROUTER_API_KEY is detected.
auxiliary_routing:
  disable: false                    # Completely disable auxiliary routing (overrides auto-enable)
  enabled: false                    # Enable auxiliary request routing
  backend: null                     # Optional: Backend to use (e.g., "openrouter")
  model: null                       # Model name (e.g., "gemini-1.5-flash" or "openrouter:gemini-1.5-flash")
  detection_patterns:               # Regex patterns to detect auxiliary requests
    - "The following is the text to summarize"
    - "Generate a (?:short |brief )?(?:title|summary|heading)"
    - "Summarize (?:the|this|my) (?:conversation|text|content|task)"
    - "Create a (?:title|heading) for"
    - "Generate a title for the (?:session|conversation)"
    - "Provide a summary of (?:the|this|my) (?:task|conversation|session)"
  max_message_count: 3              # Maximum message count for auxiliary request detection
  disable_default_openrouter: false # Disable auto-detection of OPENROUTER_API_KEY for default auxiliary model
```

### Resilience Scoping (`resilience`)

Resilience scoping controls whether rate-limit and cooldown state is shared across clients
(enterprise/shared backends) or isolated per user/session (personal OAuth/codex backends).

Defaults (no config required):

- Any backend type containing `oauth` or `codex` is treated as personal.
- The built-in personal list includes: `anthropic-oauth`, `antigravity-oauth`,
  `gemini-oauth-free`, `gemini-oauth-plan`, `gemini-cli-cloud-project`,
  `qwen-oauth`, `openai-codex`.

Use overrides only if you need to force a backend into personal or shared mode.

```yaml
resilience:
  # Force personal scoping for selected backends (optional).
  personal_backend_types: ["openai-codex", "qwen-oauth"]
  # Force shared scoping for selected backends (optional).
  shared_backend_types: ["openai", "openrouter"]
```

> **See Also:** [Resilience Scoping](features/resilience-scoping.md) and the [CLI Parameters Reference](cli-parameters.md).

### Health Check Settings (`health_check`)

Configure backend API endpoint health monitoring and circuit breaker behavior.
See [Health Checks Guide](features/health-checks.md) for complete documentation.

```yaml
health_check:
  # Master switch for health check system
  enabled: true
  
  # Circuit breaker - exclude unhealthy backends from routing
  circuit_breaker_enabled: true
  
  # Notify backend instances when their API URL health changes
  notify_backends: true
  
  # Log successful health checks (can be verbose)
  log_healthy_checks: false
  
  # ICMP Ping check configuration
  ping:
    enabled: true
    interval_seconds: 30.0      # Seconds between checks
    timeout_seconds: 5.0        # Ping timeout
    failure_threshold: 3        # Consecutive failures before marking unhealthy
  
  # HTTP probe configuration
  http:
    enabled: true
    interval_seconds: 60.0      # Seconds between checks
    timeout_seconds: 10.0       # Request timeout
    failure_threshold: 2        # Consecutive failures before marking unhealthy
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | bool | `true` | Enable the health check system |
| `circuit_breaker_enabled` | bool | `true` | Exclude unhealthy backends from routing |
| `notify_backends` | bool | `true` | Notify backend instances of health changes |
| `log_healthy_checks` | bool | `false` | Log successful checks |
| `ping.enabled` | bool | `true` | Enable ICMP ping checks |
| `ping.interval_seconds` | float | `30.0` | Seconds between ping checks |
| `ping.timeout_seconds` | float | `5.0` | Ping timeout |
| `ping.failure_threshold` | int | `3` | Failures before unhealthy |
| `http.enabled` | bool | `true` | Enable HTTP probe checks |
| `http.interval_seconds` | float | `60.0` | Seconds between HTTP checks |
| `http.timeout_seconds` | float | `10.0` | HTTP request timeout |
| `http.failure_threshold` | int | `2` | Failures before unhealthy |

### ProxyMem (Cross-Session Memory)

ProxyMem provides persistent context across sessions by capturing interactions, generating LLM summaries, and injecting relevant history into new sessions.

```yaml
memory:
  # Enable the feature
  available: true
  default_enabled: false
  
  # Models for summary and context generation
  summary_model: "openai:gpt-4o-mini"
  context_model: "openai:gpt-4o-mini"
  
  # Database
  database_path: "./var/memory.sqlite3"
  retention_days: 90
  
  # Session behavior
  session_timeout_minutes: 30
  max_context_tokens: 2000
  context_relevance_threshold: 0.5
  
  # Privacy controls
  redaction_patterns:
    - "(?i)(api[_-]?key|password|secret|token)\\s*[=:]\\s*[^\\s]*"
  disabled_users: []
  disabled_clients: []
  
  # Single-user mode (for personal deployments)
  single_user_mode: false
  fixed_user_id: null
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `available` | bool | `false` | Enable the memory feature |
| `default_enabled` | bool | `false` | Enable memory by default for new sessions |
| `summary_model` | str | `null` | Model for summary generation (`backend:model`) |
| `context_model` | str | `null` | Model for context retrieval (`backend:model`) |
| `database_path` | str | `./var/memory.sqlite3` | SQLite database location |
| `retention_days` | int | `90` | Days to retain summaries |
| `session_timeout_minutes` | int | `30` | Inactivity timeout |
| `max_context_tokens` | int | `2000` | Maximum tokens for injected context |
| `context_relevance_threshold` | float | `0.5` | Minimum relevance score |
| `single_user_mode` | bool | `false` | Use fixed user ID |

> **See Also:** [ProxyMem: Cross-Session Memory](proxymem-memory.md) for detailed documentation including commands, privacy controls, and troubleshooting.

### Database (`database`)

The proxy uses a unified database layer for storing session data, SSO tokens, and memory summaries. SQLite is the default and requires no configuration.

```yaml
database:
  # Database URL (SQLAlchemy format)
  # SQLite (default): sqlite+aiosqlite:///./var/db/proxy.db
  # PostgreSQL: postgresql+asyncpg://user:pass@host:5432/db
  url: "sqlite+aiosqlite:///./var/db/proxy.db"
  
  # Connection pool settings (PostgreSQL only)
  pool_size: 5
  max_overflow: 10
  pool_timeout: 30
  
  # Debug settings
  echo: false
  echo_pool: false
  
  # Auto-run migrations on startup
  auto_migrate: true
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `url` | str | `sqlite+aiosqlite:///./var/db/proxy.db` | Database connection URL |
| `pool_size` | int | `5` | Connection pool size (PostgreSQL only) |
| `max_overflow` | int | `10` | Extra connections beyond pool_size |
| `pool_timeout` | int | `30` | Seconds to wait for connection |
| `echo` | bool | `false` | Log SQL statements (debug) |
| `auto_migrate` | bool | `true` | Run migrations on startup |

> **See Also:** [Database Configuration](database-configuration.md) for detailed setup including PostgreSQL examples, migrations, and production recommendations.

### Other Settings

```yaml
# Empty Response Handling
empty_response:
  enabled: true
  max_retries: 1

# Model Name Rewrites
model_aliases:
  - pattern: "^gpt-4-(.*)"
    replacement: "openai:gpt-4-\1"

# Reasoning Aliases (Shorthands)
reasoning_aliases:
  reasoning_alias_settings: []
```
