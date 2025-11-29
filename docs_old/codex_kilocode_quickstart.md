# Codex-KiloCode Compatibility Layer Quick Start

## 5-Minute Setup Guide

### Prerequisites

- LLM Interactive Proxy installed and running
- OpenAI API key with Codex access
- KiloCode client configured

### Step 1: Create Configuration (2 minutes)

Create `config/backends/openai_codex/backend.yaml`:

```yaml
backend_type: "openai-codex"
timeout: 120

compatibility_layer:
  enabled: true
  
  detection:
    cache_ttl_seconds: 3600
  
  translation:
    max_tool_execution_timeout: 30
  
  telemetry:
    log_translations: true
    emit_metrics: true
```

### Step 2: Configure Main Proxy (1 minute)

Add to `config/config.yaml`:

```yaml
backends:
  openai-codex:
    timeout: 120
    config_file: "config/backends/openai_codex/backend.yaml"
```

### Step 3: Set API Key (30 seconds)

```bash
export OPENAI_API_KEY="your-api-key-here"
```

### Step 4: Restart Proxy (30 seconds)

```bash
python -m src.core.cli
```

### Step 5: Verify (1 minute)

Check logs for:
```
INFO: Codex-Kilo compatibility layer activated
```

## Common Configuration Scenarios

### Scenario 1: Maximum Security

```yaml
compatibility_layer:
  enabled: true
  translation:
    tools:
      execute_command: false
      write_to_file: false
    file_operations:
      restrict_to_workspace: true
      blocked_patterns:
        - "**/.env*"
        - "**/*.key"
        - "**/*.pem"
```

### Scenario 2: Development Mode

```yaml
compatibility_layer:
  enabled: true
  translation:
    max_tool_execution_timeout: 60
  telemetry:
    log_level: "DEBUG"
    log_translations: true
    log_detection: true
```

### Scenario 3: Production Mode

```yaml
compatibility_layer:
  enabled: true
  translation:
    max_tool_execution_timeout: 30
  telemetry:
    log_level: "INFO"
    emit_metrics: true
    include_xml_in_errors: false
  error_handling:
    detailed_errors: false
```

### Scenario 4: Minimal Configuration

```yaml
compatibility_layer:
  enabled: true
```

All other settings use defaults.

## Quick Troubleshooting

### Problem: Compatibility layer not activating

**Check:**
1. `enabled: true` in config
2. Client sends agent metadata
3. Logs show detection events

**Fix:**
```yaml
detection:
  methods:
    metadata: true
    header: true
    heuristic: true
```

### Problem: Tool not working

**Check:**
1. Tool in supported list
2. Tool enabled in config
3. XML syntax correct

**Fix:**
```yaml
translation:
  tools:
    read_file: true  # Enable tool
```

### Problem: Slow performance

**Check:**
1. Detection cache working
2. Tool execution timeout
3. System resources

**Fix:**
```yaml
detection:
  cache_ttl_seconds: 7200  # Increase cache TTL
translation:
  max_tool_execution_timeout: 15  # Reduce timeout
```

### Problem: Permission errors

**Check:**
1. File/directory permissions
2. Workspace restrictions
3. Blocked patterns

**Fix:**
```yaml
translation:
  file_operations:
    restrict_to_workspace: true
    blocked_patterns: []  # Clear if needed
```

## Quick Commands

### Validate Configuration

```bash
python -c "
from src.connectors.openai_codex_config import load_and_validate_config
config, errors = load_and_validate_config('config/backends/openai_codex/backend.yaml')
print('Valid!' if not errors else f'Errors: {errors}')
"
```

### Check Metrics

```bash
curl http://localhost:8000/metrics | grep compatibility_layer
```

### View Logs

```bash
tail -f logs/proxy.log | grep "compatibility"
```

### Test Detection

```bash
# Send test request with KiloCode agent
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "User-Agent: KiloCode/1.0.0" \
  -d '{
    "model": "openai-codex:gpt-4-codex",
    "messages": [{"role": "user", "content": "test"}]
  }'
```

## Quick Reference

### Supported Tools

✅ File: `read_file`, `list_files`, `write_to_file`, `insert_content`, `edit_file`
✅ Search: `codebase_search`, `search_files`
✅ Command: `execute_command`
✅ Edit: `search_and_replace`, `use_mcp_tool` (patch_file)
✅ MCP: `access_mcp_resource`, `use_mcp_tool`
✅ Control: `attempt_completion`, `ask_followup_question`

❌ Unsupported: `browser_action`, `screenshot`, `inspect_site`

### Error Codes

- `COMPAT_E001`: Unsupported tool
- `COMPAT_E002`: Invalid XML syntax
- `COMPAT_E003`: Parameter validation failed
- `COMPAT_E004`: Tool execution failed
- `COMPAT_E005`: MCP bridge error
- `COMPAT_E006`: Detection failed
- `COMPAT_E007`: Translation timeout

### Configuration Limits

| Setting | Min | Max | Default |
|---------|-----|-----|---------|
| cache_ttl_seconds | 0 | 86400 | 3600 |
| heuristic_threshold | 1 | 10 | 2 |
| max_tool_execution_timeout | 1 | 300 | 30 |
| max_output_size | 1024 | 100MB | 1MB |
| max_file_size | 1024 | 1GB | 10MB |

## Next Steps

1. **Read Full Documentation**: [Codex-KiloCode Compatibility](./codex_kilocode_compatibility.md)
2. **Review Error Codes**: [Error Codes and Troubleshooting](./codex_kilocode_error_codes.md)
3. **Check Supported Tools**: [Supported Tools and Limitations](./codex_kilocode_tools.md)
4. **Set Up Monitoring**: Configure metrics and alerts
5. **Test Thoroughly**: Run integration tests

## Getting Help

- **Documentation**: See `docs/codex_kilocode_*.md` files
- **Logs**: Check `logs/proxy.log` with DEBUG level
- **Metrics**: Query Prometheus metrics endpoint
- **Issues**: File issue with logs and configuration

## Cheat Sheet

```bash
# Enable compatibility layer
sed -i 's/enabled: false/enabled: true/' config/backends/openai_codex/backend.yaml

# Disable compatibility layer
sed -i 's/enabled: true/enabled: false/' config/backends/openai_codex/backend.yaml

# Validate config
python -c "from src.connectors.openai_codex_config import load_and_validate_config; print(load_and_validate_config('config/backends/openai_codex/backend.yaml')[1])"

# Check metrics
curl -s http://localhost:8000/metrics | grep compatibility_layer

# Watch logs
tail -f logs/proxy.log | grep -i "compat\|kilocode"

# Test detection
curl -X POST http://localhost:8000/v1/chat/completions -H "User-Agent: KiloCode/1.0.0" -d '{"model":"openai-codex:gpt-4-codex","messages":[{"role":"user","content":"test"}]}'
```
