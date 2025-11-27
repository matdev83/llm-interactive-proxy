# CLI Parameters and Configuration Reference

This guide documents all available CLI parameters, environment variables, and configuration options for the LLM Interactive Proxy.

## Configuration Precedence

Configuration is resolved in the following order (highest to lowest priority):

1. **CLI Arguments** - Command-line flags override everything
2. **Environment Variables** - Environment variables override config files
3. **YAML Configuration File** - Config file provides defaults
4. **Built-in Defaults** - Hardcoded defaults if nothing else is specified

## Backend Configuration

### Default Backend

**CLI Argument:**
```bash
--default-backend openai|anthropic|gemini|openrouter|zai|qwen
```

**Environment Variable:**
```bash
export DEFAULT_BACKEND=openai
```

**YAML Configuration:**
```yaml
backends:
  default_backend: openai
```

### API Keys

**Environment Variables:**
```bash
# Single key
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="..."
export OPENROUTER_API_KEY="sk-or-..."
export ZAI_API_KEY="..."
export QWEN_API_KEY="..."

# Multiple keys (numbered)
export OPENAI_API_KEY_1="sk-..."
export OPENAI_API_KEY_2="sk-..."
export OPENAI_API_KEY_3="sk-..."
```

**YAML Configuration:**
```yaml
backends:
  openai:
    api_keys:
      - "sk-..."
      - "sk-..."
  anthropic:
    api_keys:
      - "sk-ant-..."
```

## Server Configuration

### Host and Port

**CLI Arguments:**
```bash
--host 0.0.0.0
--port 8000
--anthropic-port 8001
```

**Environment Variables:**
```bash
export HOST=0.0.0.0
export PORT=8000
export ANTHROPIC_PORT=8001
```

**YAML Configuration:**
```yaml
server:
  host: 0.0.0.0
  port: 8000
  anthropic_port: 8001
```

## Authentication

### API Key Authentication

**CLI Arguments:**
```bash
--auth-token "your-secret-key"
--disable-auth  # Disable authentication
```

**Environment Variables:**
```bash
export AUTH_TOKEN="your-secret-key"
export DISABLE_AUTH=false
```

**YAML Configuration:**
```yaml
auth:
  token: "your-secret-key"
  enabled: true
```

### API Key Redaction

**CLI Arguments:**
```bash
--disable-redact-api-keys-in-prompts  # Disable API key redaction
```

**Environment Variables:**
```bash
export REDACT_API_KEYS_IN_PROMPTS=true
```

**YAML Configuration:**
```yaml
auth:
  redact_api_keys_in_prompts: true
```

## Feature Configuration

### LLM Assessment System

**CLI Arguments:**
```bash
--enable-llm-assessment
--llm-assessment-backend openai
--llm-assessment-model gpt-4o-mini
--llm-assessment-turn-threshold 30
--llm-assessment-confidence-threshold 0.9
--llm-assessment-history-window 20
```

**Environment Variables:**
```bash
export LLM_ASSESSMENT_ENABLED=true
export LLM_ASSESSMENT_BACKEND=openai
export LLM_ASSESSMENT_MODEL=gpt-4o-mini
export LLM_ASSESSMENT_TURN_THRESHOLD=30
export LLM_ASSESSMENT_CONFIDENCE_THRESHOLD=0.9
export LLM_ASSESSMENT_HISTORY_WINDOW=20
```

### Angel Verification System

**CLI Arguments:**
```bash
--use-angel-model "backend:model"
--angel-frequency 1
```

**Environment Variables:**
```bash
export ANGEL_MODEL="openai:gpt-4o-mini"
export ANGEL_FREQUENCY=1
```

### Edit Precision Tuning

**CLI Arguments:**
```bash
--enable-edit-precision
--disable-edit-precision
--edit-precision-temperature 0.1
--edit-precision-min-top-p 0.3
--edit-precision-override-top-p
--edit-precision-exclude-agents "regex-pattern"
```

**Environment Variables:**
```bash
export EDIT_PRECISION_ENABLED=true
export EDIT_PRECISION_TEMPERATURE=0.1
export EDIT_PRECISION_MIN_TOP_P=0.3
export EDIT_PRECISION_OVERRIDE_TOP_P=false
export EDIT_PRECISION_EXCLUDE_AGENTS_REGEX="pattern"
```

### Dangerous Command Protection

**CLI Arguments:**
```bash
--disable-dangerous-git-commands-protection
```

**Environment Variables:**
```bash
export DANGEROUS_COMMAND_PREVENTION_ENABLED=true
```

### File Access Sandboxing

**CLI Arguments:**
```bash
--enable-sandboxing
```

**Environment Variables:**
```bash
export ENABLE_SANDBOXING=true
```

### Tool Access Control

**CLI Arguments:**
```bash
--allowed-tools "read_.*,list_.*"
--blocked-tools "delete_.*,rm_.*"
--default-policy allow|deny
```

**Environment Variables:**
```bash
export ALLOWED_TOOLS="read_.*,list_.*"
export BLOCKED_TOOLS="delete_.*,rm_.*"
export DEFAULT_POLICY=allow
```

### Think Tags Fix

**CLI Arguments:**
```bash
--fix-think-tags
--fix-think-tags-streaming-buffer-size 4096
```

**Environment Variables:**
```bash
export FIX_THINK_TAGS_ENABLED=true
export FIX_THINK_TAGS_STREAMING_BUFFER_SIZE=4096
```

### Model Name Rewrites

**CLI Arguments:**
```bash
--model-name-rewrites "gpt-4:openai:gpt-4-turbo"
```

**Environment Variables:**
```bash
export MODEL_NAME_REWRITES="gpt-4:openai:gpt-4-turbo"
```

### Planning Phase Overrides

**CLI Arguments:**
```bash
--planning-phase-model "backend:model"
--planning-phase-turns 5
--planning-phase-temperature 0.7
```

**Environment Variables:**
```bash
export PLANNING_PHASE_MODEL="openai:gpt-4"
export PLANNING_PHASE_TURNS=5
export PLANNING_PHASE_TEMPERATURE=0.7
```

### Session Management

**CLI Arguments:**
```bash
--session-timeout 3600
--max-sessions 100
```

**Environment Variables:**
```bash
export SESSION_TIMEOUT=3600
export MAX_SESSIONS=100
```

### Context Window Enforcement

**CLI Arguments:**
```bash
--enforce-context-window
--context-window-buffer 500
```

**Environment Variables:**
```bash
export ENFORCE_CONTEXT_WINDOW=true
export CONTEXT_WINDOW_BUFFER=500
```

## Debugging and Logging

### Wire Capture

**CLI Arguments:**
```bash
--enable-wire-capture
--wire-capture-format json|cbor
--wire-capture-output-dir ./var/wire_captures
```

**Environment Variables:**
```bash
export ENABLE_WIRE_CAPTURE=true
export WIRE_CAPTURE_FORMAT=json
export WIRE_CAPTURE_OUTPUT_DIR=./var/wire_captures
```

### Logging

**CLI Arguments:**
```bash
--log-level DEBUG|INFO|WARNING|ERROR
--log-file ./var/logs/proxy.log
```

**Environment Variables:**
```bash
export LOG_LEVEL=INFO
export LOG_FILE=./var/logs/proxy.log
```

## Client Identity Override

**CLI Arguments:**
```bash
--identity-user-agent "MyApp/1.0.0"
--identity-referer "https://myapp.com"
--identity-x-title "My Application"
```

**Environment Variables:**
```bash
export IDENTITY_USER_AGENT="MyApp/1.0.0"
export IDENTITY_REFERER="https://myapp.com"
export IDENTITY_X_TITLE="My Application"
```

## Configuration File

**CLI Argument:**
```bash
--config path/to/config.yaml
```

**Environment Variable:**
```bash
export CONFIG_FILE=path/to/config.yaml
```

## Example Configuration File

```yaml
# config.yaml
server:
  host: 0.0.0.0
  port: 8000
  anthropic_port: 8001

backends:
  default_backend: openai
  openai:
    api_keys:
      - "sk-..."
  anthropic:
    api_keys:
      - "sk-ant-..."

auth:
  token: "your-secret-key"
  enabled: true
  redact_api_keys_in_prompts: true

session:
  llm_assessment:
    enabled: true
    backend: openai
    model: gpt-4o-mini
    turn_threshold: 30
    confidence_threshold: 0.9
  
  angel_model: "openai:gpt-4o-mini"
  angel_frequency: 1
  
  edit_precision:
    enabled: true
    temperature: 0.1
    min_top_p: 0.3
  
  dangerous_command_prevention_enabled: true
  
  sandboxing:
    enabled: true
  
  fix_think_tags_enabled: true

logging:
  level: INFO
  file: ./var/logs/proxy.log

wire_capture:
  enabled: false
  format: json
  output_dir: ./var/wire_captures
```

## Common Configuration Scenarios

### Development Setup

```bash
export DEFAULT_BACKEND=openai
export OPENAI_API_KEY="sk-..."
export LOG_LEVEL=DEBUG
export ENABLE_WIRE_CAPTURE=true
```

### Production Setup

```bash
export DEFAULT_BACKEND=openai
export OPENAI_API_KEY_1="sk-..."
export OPENAI_API_KEY_2="sk-..."
export AUTH_TOKEN="your-secret-key"
export DANGEROUS_COMMAND_PREVENTION_ENABLED=true
export ENABLE_SANDBOXING=true
export LOG_LEVEL=INFO
```

### Testing Setup

```bash
export DEFAULT_BACKEND=openai
export OPENAI_API_KEY="sk-test-..."
export DISABLE_AUTH=true
export LLM_ASSESSMENT_ENABLED=false
export LOG_LEVEL=DEBUG
```

## Troubleshooting

### Configuration Not Applied

1. Check precedence - CLI arguments override environment variables
2. Verify environment variable names are correct (case-sensitive on Linux)
3. Check YAML syntax if using config file
4. Restart the proxy after changing configuration

### API Key Issues

1. Verify API key format is correct for the backend
2. Check that API key environment variable is set
3. Ensure API key has necessary permissions
4. Check logs for authentication errors

### Feature Not Working

1. Verify feature is enabled via CLI or environment variable
2. Check that required dependencies are configured
3. Review logs for feature-specific errors
4. Consult feature-specific documentation

## Related Documentation

- [Configuration Guide](./configuration.md) - Detailed configuration overview
- [User Guide Index](./index.md) - All user documentation
- [Development Guide](../development_guide/index.md) - Developer documentation
