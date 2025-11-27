# Configuration Guide

The LLM Interactive Proxy supports multiple configuration methods with a clear precedence order. This guide explains how to configure the proxy using CLI arguments, environment variables, and YAML configuration files.

## Configuration Precedence

Configuration values are resolved in the following order (highest to lowest priority):

1. **CLI Arguments** - Command-line flags (highest priority)
2. **Environment Variables** - Shell environment variables
3. **YAML Configuration File** - Configuration file specified with `--config`
4. **Default Values** - Built-in defaults (lowest priority)

When the same setting is specified in multiple places, the higher priority source wins.

### Example

```bash
# Config file sets temperature to 0.7
# Environment variable sets temperature to 0.5
export TEMPERATURE=0.5
# CLI argument sets temperature to 0.3
python -m src.core.cli --temperature 0.3 --config config.yaml

# Result: temperature = 0.3 (CLI wins)
```

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
  --force-model gpt-4o-mini \
  --enable-edit-precision \
  --disable-auth
```

See the [Quick Start Guide](quick-start.md#useful-cli-flags) for a list of common CLI flags.

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

# Proxy Configuration
export LLM_INTERACTIVE_PROXY_API_KEY=your-proxy-key
export ANTHROPIC_PORT=8001
export FORCE_CONTEXT_WINDOW=8000

# Feature Toggles
export DANGEROUS_COMMAND_PREVENTION_ENABLED=true  # [Dangerous Command Protection](features/dangerous-command-protection.md)
export EDIT_PRECISION_ENABLED=true                # [Edit Precision](features/edit-precision.md)
export FIX_THINK_TAGS_ENABLED=true                # [Think Tags Fix](features/think-tags-fix.md)
export STRICT_COMMAND_DETECTION=true

# [LLM Assessment](features/llm-assessment.md)
export LLM_ASSESSMENT_ENABLED=true
export LLM_ASSESSMENT_BACKEND=openai
export LLM_ASSESSMENT_MODEL=gpt-4o-mini

# [Angel Verification](features/angel-verification.md)
export ANGEL_MODEL="openai:gpt-4o-mini"
export ANGEL_FREQUENCY=1

# [Edit Precision](features/edit-precision.md)
export EDIT_PRECISION_TEMPERATURE=0.1
export EDIT_PRECISION_MIN_TOP_P=0.3
export EDIT_PRECISION_OVERRIDE_TOP_P=false

# Gemini OAuth
export DISABLE_GEMINI_OAUTH_FALLBACK=false

# GCP Gemini
export GOOGLE_CLOUD_PROJECT=your-project-id
```

### 3. YAML Configuration Files

YAML configuration files are best for:

- Persistent configuration across sessions
- Complex multi-backend setups
- Team-shared configurations
- Documenting your setup

**Minimal Configuration Example**:

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

**Run with config file**:

```bash
python -m src.core.cli --config config.yaml
```

## Configuration File Structure

### Basic Structure

```yaml
# Backend Configuration
backends:
  openai:
    type: openai
  anthropic:
    type: anthropic
  gemini:
    type: gemini

# Default backend to use
default_backend: openai

# Proxy server settings
proxy:
  host: 0.0.0.0
  port: 8000

# Authentication settings
auth:
  disable_auth: false

# Session settings
session:
  # [Dangerous command protection](features/dangerous-command-protection.md)
  dangerous_command_prevention_enabled: true
  
  # Strict command detection
  strict_command_detection: false
  
  # [Think tags fix](features/think-tags-fix.md)
  fix_think_tags_enabled: false
  fix_think_tags_streaming_buffer_size: 4096
  
  # [Angel verification](features/angel-verification.md)
  angel_model: null
  angel_frequency: 1
  
  # [Tool call reactor](features/tool-access-control.md)
  tool_call_reactor:
    enabled: true
    access_policies: []

# [Edit precision tuning](features/edit-precision.md)
edit_precision:
  enabled: true
  temperature: 0.1
  min_top_p: 0.3
  override_top_p: false
  exclude_agents_regex: null

# [LLM Assessment](features/llm-assessment.md)
llm_assessment:
  enabled: false
  backend: openai
  model: gpt-4o-mini
  turn_threshold: 30
  confidence_threshold: 0.9
  history_window: 20
  intervals:
    min: 5
    max: 15
    default: 3

# [Model aliases (rewrites)](features/model-name-rewrites.md)
model_aliases: []

# [Identity override](features/identity-override.md)
identity:
  user_agent:
    mode: passthrough  # passthrough, override, or default
    override_value: null
  http_referer:
    mode: passthrough
    override_value: null
  x_title:
    mode: passthrough
    override_value: null
```

### Backend-Specific Configuration

Each backend can have its own configuration file in `config/backends/<backend-name>/backend.yaml`:

```yaml
# config/backends/gemini-cli-acp/backend.yaml
project_dir: "/path/to/your/project"
auto_accept: false
```

See the [Backend Documentation](backends/overview.md) for backend-specific configuration options.

## Common Configuration Scenarios

### Local Development (No Auth)

```yaml
proxy:
  host: 127.0.0.1
  port: 8000
auth:
  disable_auth: true
default_backend: openai
```

```bash
python -m src.core.cli --config config.yaml
```

### Production (With Auth)

```yaml
proxy:
  host: 0.0.0.0
  port: 8000
auth:
  disable_auth: false  # Requires LLM_INTERACTIVE_PROXY_API_KEY env var
default_backend: openai
session:
  dangerous_command_prevention_enabled: true
```

```bash
export LLM_INTERACTIVE_PROXY_API_KEY=your-secure-key
python -m src.core.cli --config config.yaml
```

### Multi-Backend Setup

```yaml
backends:
  openai:
    type: openai
  anthropic:
    type: anthropic
  gemini:
    type: gemini
  openrouter:
    type: openrouter

default_backend: openai

proxy:
  host: 0.0.0.0
  port: 8000
```

Users can switch backends at runtime with `!/backend(anthropic)`.

### Force Specific Model

```bash
# Override all model requests to use gemini-2.5-pro
python -m src.core.cli \
  --default-backend gemini-oauth-plan \
  --force-model gemini-2.5-pro \
  --config config.yaml
```

### Enable All Safety Features

```yaml
session:
  dangerous_command_prevention_enabled: true
  strict_command_detection: true
  tool_call_reactor:
    enabled: true
    access_policies:
      - name: block_dangerous_ops
        model_pattern: ".*"
        default_policy: allow
        blocked_patterns:
          - "delete_.*"
          - "rm_.*"
          - "remove_.*"
        block_message: "Destructive operations are not allowed."

llm_assessment:
  enabled: true
  backend: openai
  model: gpt-4o-mini
  turn_threshold: 30
  confidence_threshold: 0.9
```

### Enable Debugging

```bash
# Enable wire capture for debugging
python -m src.core.cli \
  --config config.yaml \
  --capture-file var/wire_captures_json/debug.log \
  --cbor-capture-file var/wire_captures_cbor/debug.cbor
```

## Configuration Files Location

The proxy looks for configuration files in these locations:

- **Specified via CLI**: `--config /path/to/config.yaml`
- **Backend-specific**: `config/backends/<backend-name>/backend.yaml`
- **Example configs**: `config/config.example.yaml`

## Validating Your Configuration

To verify your configuration is loaded correctly:

1. Start the proxy with your config file
2. Check the startup logs for configuration values
3. Look for any warnings about invalid settings
4. Test with a simple request to verify behavior

## Related Documentation

- [Quick Start Guide](quick-start.md) - Get started quickly
- [Backend Configuration](backends/overview.md) - Backend-specific setup
- [Feature Configuration](features/) - Feature-specific settings
- [Security Configuration](security/authentication.md) - Authentication and security
- [Tool Access Control](features/tool-access-control.md) - Fine-grained tool permissions
- [LLM Assessment](features/llm-assessment.md) - Conversation quality monitoring
- [Edit Precision](features/edit-precision.md) - Automated parameter tuning

## Example Configuration Files

The `config/` directory includes several example configuration files:

- `config.example.yaml` - Basic configuration template
- `identity_kilocode.example.yaml` - KiloCode client identity
- `identity_factory_droid.example.yaml` - Factory Droid client identity
- `tool_access_control_examples.yaml` - Tool access control policies
- `edit_precision_model_temperatures.yaml` - Per-model temperature overrides
- `reasoning_aliases.yaml.example` - Custom reasoning aliases

Copy and modify these examples to create your own configuration.
