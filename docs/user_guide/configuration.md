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
  --host 0.0.0.0 \
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

# Proxy Configuration
export APP_HOST=0.0.0.0
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
anthropic_port: 8001           # Port for Anthropic-compatible endpoints
proxy_timeout: 120             # Global request timeout (seconds)
command_prefix: "!/"           # Command prefix for in-chat commands
strict_command_detection: false # Require commands to be at start of message
context_window_override: null  # Override context window size (int)
disable_health_checks: false   # Disable health check endpoints
gcp_project_id: null           # Google Cloud Project ID
gemini_credentials_path: null  # Path to Gemini credentials JSON
```

### Backend Settings (`backends`)

```yaml
backends:
  default_backend: "openai"    # Default backend identifier
  static_route: null           # Force all traffic to "backend:model"
  disable_gemini_oauth_fallback: false
  disable_hybrid_backend: false
  hybrid_backend_repeat_messages: false
  reasoning_injection_probability: 1.0
  hybrid_reasoning_model_timeout: 60
  hybrid_reasoning_force_initial_turns: 1
  hybrid_execution_model_timeout: 120
  
  # Backend-specific configurations
  openai:
    api_key: ["sk-..."]        # List of API keys
    api_url: "https://api.openai.com/v1"
    timeout: 120
    models: []                 # Optional list of supported models
    
  anthropic:
    api_key: ["sk-ant-..."]
    api_url: "https://api.anthropic.com/v1"
    
  gemini:
    api_key: ["..."]
    api_url: "https://generativelanguage.googleapis.com"
    
  openrouter:
    api_key: ["sk-or-..."]
    api_url: "https://openrouter.ai/api/v1"

  minimax:
    api_key: ["..."]
    api_url: "https://api.minimax.io/v1"
    
  # Custom/Other backends follow the same structure
```

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
  
  # Angel Verification
  angel_model: null            # "backend:model"
  angel_frequency: 1
  
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

### LLM Assessment (`assessment`)

```yaml
assessment:
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
```

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
