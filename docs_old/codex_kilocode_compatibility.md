# Codex-KiloCode Compatibility Layer

## Overview

The Codex-KiloCode Compatibility Layer enables seamless communication between KiloCode clients and the OpenAI Codex backend. This layer translates KiloCode's XML-style tool invocations into Codex-compatible format while preserving Codex's canonical system instructions.

## Key Features

- **Automatic Client Detection**: Identifies KiloCode clients using metadata, headers, and heuristic analysis
- **Tool Translation**: Converts KiloCode XML tool invocations to Codex-compatible format
- **Prompt Preservation**: Maintains Codex's canonical instructions byte-for-byte
- **Zero Impact**: No performance overhead for non-KiloCode clients
- **Configurable**: Extensive configuration options for security and behavior
- **Observable**: Comprehensive telemetry and logging for monitoring

## Architecture

The compatibility layer operates as conditional middleware that activates only when:
1. The backend is set to `openai-codex`
2. The client is identified as KiloCode
3. The compatibility layer is enabled in configuration

When activated, the layer:
1. Detects KiloCode clients and caches the result
2. Preserves Codex's canonical instructions
3. Translates XML tool invocations to Codex format
4. Executes tools proxy-side when Codex doesn't provide native support
5. Formats results in KiloCode's expected format

## Enabling the Compatibility Layer

### Step 1: Create Backend Configuration

Create or edit `config/backends/openai_codex/backend.yaml`:

```yaml
# OpenAI Codex Backend Configuration
backend_type: "openai-codex"
timeout: 120

compatibility_layer:
  enabled: true  # Enable the compatibility layer
  
  detection:
    cache_ttl_seconds: 3600
    heuristic_threshold: 2
  
  translation:
    max_tool_execution_timeout: 30
    result_format: "kilo_standard"
  
  telemetry:
    log_translations: true
    log_detection: true
    emit_metrics: true
```

### Step 2: Configure Main Proxy

Add the Codex backend to your main `config/config.yaml`:

```yaml
backends:
  default_backend: "openai"
  
  openai-codex:
    timeout: 120
    config_file: "config/backends/openai_codex/backend.yaml"
```

### Step 3: Set Environment Variables

Set the OpenAI API key:

```bash
export OPENAI_API_KEY="your-api-key-here"
```

### Step 4: Restart the Proxy

Restart the LLM Interactive Proxy to load the new configuration:

```bash
python -m src.core.cli
```

### Step 5: Verify Activation

Check the logs for compatibility layer activation:

```
INFO: Codex-Kilo compatibility layer activated
  session_id: abc123
  detection_method: metadata
  agent: kilocode/1.0.0
  confidence: 1.0
```

## Configuration Options

### Global Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Global enable/disable flag |

### Detection Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `cache_ttl_seconds` | integer | `3600` | Cache TTL for detection results (seconds) |
| `heuristic_threshold` | integer | `2` | Min XML tags for heuristic detection |
| `methods.metadata` | boolean | `true` | Enable metadata-based detection |
| `methods.header` | boolean | `true` | Enable header-based detection |
| `methods.heuristic` | boolean | `true` | Enable heuristic detection |

### Translation Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `max_tool_execution_timeout` | integer | `30` | Max timeout for tool execution (seconds) |
| `result_format` | string | `"kilo_standard"` | Result format (`kilo_standard` or `verbose`) |
| `tools.*` | boolean | `true` | Enable/disable specific tools |

### Command Execution Security

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `allowed_shells` | array | `["bash", "sh", "cmd", "powershell"]` | Allowed shells |
| `restrict_to_workspace` | boolean | `true` | Restrict to workspace directory |
| `max_output_size` | integer | `1048576` | Max command output size (bytes) |

### File Operations Security

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `restrict_to_workspace` | boolean | `true` | Restrict to workspace directory |
| `max_file_size` | integer | `10485760` | Max file size for reads (bytes) |
| `allowed_extensions` | array | `[]` | Allowed file extensions (empty = all) |
| `blocked_patterns` | array | See config | Blocked file patterns (glob) |

### Telemetry Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `log_translations` | boolean | `true` | Log translation events |
| `log_detection` | boolean | `true` | Log detection events |
| `emit_metrics` | boolean | `true` | Emit Prometheus metrics |
| `log_level` | string | `"INFO"` | Log level for compatibility layer |
| `include_xml_in_errors` | boolean | `false` | Include XML in error logs |

### Error Handling Settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `detailed_errors` | boolean | `true` | Return detailed error messages |
| `include_suggestions` | boolean | `true` | Include suggestions in errors |
| `fail_fast` | boolean | `true` | Stop on first translation error |

## Supported Tools

The compatibility layer supports the following KiloCode tools:

### File Operations
- `<read_file>` - Read file contents
- `<list_files>` - List directory contents
- `<write_to_file>` - Write content to file
- `<insert_content>` - Insert content at position
- `<edit_file>` - Edit file with instructions

### Search Operations
- `<codebase_search>` - Search codebase with pattern
- `<search_files>` - Search files with glob patterns

### Command Execution
- `<execute_command>` - Execute shell commands

### Editing Operations
- `<search_and_replace>` - Search and replace in files
- `<use_mcp_tool>` - Use MCP tools (including patch_file)

### MCP Integration
- `<access_mcp_resource>` - Access MCP resources
- `<use_mcp_tool>` - Generic MCP tool invocation

### Conversation Control
- `<attempt_completion>` - Mark task as complete
- `<ask_followup_question>` - Ask follow-up question

## Known Limitations

### Unsupported Tools
The following KiloCode tools are **not supported**:
- `<browser_action>` - Browser automation
- `<screenshot>` - Screen capture
- `<inspect_site>` - Website inspection

### Codex Constraints
- Codex requires canonical instructions (cannot be modified)
- Codex has limited context window (8K tokens)
- Codex may not support all MCP tools

### Performance Considerations
- Detection adds <5ms latency per request (first request only)
- Translation adds <50ms latency per tool invocation
- Proxy-side execution may be slower than native Codex tools

## Disabling the Compatibility Layer

### Temporary Disable (No Restart Required)

Set the `enabled` flag to `false` in `config/backends/openai_codex/backend.yaml`:

```yaml
compatibility_layer:
  enabled: false
```

The proxy will reload the configuration automatically.

### Permanent Disable

Remove or comment out the `compatibility_layer` section entirely:

```yaml
# compatibility_layer:
#   enabled: false
```

### Per-Tool Disable

Disable specific tools while keeping the layer active:

```yaml
compatibility_layer:
  enabled: true
  translation:
    tools:
      execute_command: false  # Disable command execution
      write_to_file: false    # Disable file writes
```

## Monitoring and Observability

### Metrics

The compatibility layer emits the following Prometheus metrics:

```
# Detection metrics
compatibility_layer_detection_total{method="metadata|header|heuristic", result="kilocode|other"}
compatibility_layer_detection_duration_seconds{method="metadata|header|heuristic"}
compatibility_layer_cache_hit_total{result="hit|miss"}

# Translation metrics
compatibility_layer_translation_total{tool="read_file|...", result="success|error"}
compatibility_layer_translation_duration_seconds{tool="read_file|..."}
compatibility_layer_tool_execution_total{tool="...", executor="codex|proxy"}

# Error metrics
compatibility_layer_error_total{error_code="COMPAT_E001|..."}
compatibility_layer_unsupported_tool_total{tool="browser_action|..."}
```

### Logging

Enable detailed logging by setting the log level:

```yaml
telemetry:
  log_level: "DEBUG"
  log_translations: true
  log_detection: true
```

Example log output:

```
INFO: Codex-Kilo compatibility layer activated
  session_id: abc123
  detection_method: metadata
  agent: kilocode/1.0.0

DEBUG: Translating KiloCode tool invocation
  session_id: abc123
  tool_name: read_file
  original_xml: <read_file>src/main.py</read_file>
  translated_tool: read_file
  execution_mode: proxy
```

## Security Best Practices

### 1. Restrict File Access

Always enable workspace restrictions:

```yaml
translation:
  file_operations:
    restrict_to_workspace: true
    blocked_patterns:
      - "**/.env"
      - "**/.env.*"
      - "**/id_rsa"
      - "**/*.key"
```

### 2. Limit Command Execution

Restrict allowed shells and workspace:

```yaml
translation:
  command_execution:
    allowed_shells: ["bash", "sh"]
    restrict_to_workspace: true
    max_output_size: 1048576
```

### 3. Disable Sensitive Tools

Disable tools that aren't needed:

```yaml
translation:
  tools:
    execute_command: false
    write_to_file: false
```

### 4. Monitor for Abuse

Enable metrics and set up alerts:

```yaml
telemetry:
  emit_metrics: true
  log_translations: true
```

Set up alerts for:
- High error rates
- Unusual tool usage patterns
- Excessive command execution

### 5. Sanitize Error Messages

In production, disable XML in error logs:

```yaml
telemetry:
  include_xml_in_errors: false
```

## Troubleshooting

See [Error Codes and Troubleshooting](./codex_kilocode_error_codes.md) for detailed troubleshooting guidance.

### Common Issues

#### Compatibility Layer Not Activating

**Symptoms**: KiloCode client not detected, no translation occurring

**Solutions**:
1. Check that `enabled: true` in configuration
2. Verify client sends agent metadata or User-Agent header
3. Enable heuristic detection as fallback
4. Check logs for detection events

#### Tool Translation Failures

**Symptoms**: Error messages about unsupported tools

**Solutions**:
1. Check that tool is in supported list
2. Verify tool is enabled in configuration
3. Check XML syntax is correct
4. Review error logs for details

#### Performance Issues

**Symptoms**: Slow response times, high latency

**Solutions**:
1. Check detection cache is working (cache hit metrics)
2. Reduce `max_tool_execution_timeout`
3. Disable verbose logging in production
4. Profile tool execution times

#### Codex Rejecting Requests

**Symptoms**: HTTP 400 errors from Codex

**Solutions**:
1. Verify canonical instructions are preserved
2. Check that client personas are in user blocks
3. Review prompt handling logic
4. Check for ASCII sanitization issues

## Migration Guide

### From Direct Codex Integration

If you're currently using Codex directly without the compatibility layer:

1. **Backup Configuration**: Save your current configuration
2. **Add Backend Config**: Create `config/backends/openai_codex/backend.yaml`
3. **Enable Layer**: Set `enabled: true`
4. **Test with KiloCode**: Verify KiloCode clients work
5. **Monitor**: Watch logs and metrics for issues
6. **Rollback Plan**: Keep `enabled: false` config ready

### From Other Backends

If you're migrating from another backend (e.g., OpenRouter):

1. **Update Backend**: Change `default_backend` to `openai-codex`
2. **Configure Layer**: Set up compatibility layer config
3. **Test Tools**: Verify all tools work as expected
4. **Adjust Timeouts**: Codex may have different latency
5. **Monitor Costs**: Track API usage and costs

## Support

For issues or questions:

1. Check the [Error Codes documentation](./codex_kilocode_error_codes.md)
2. Review logs with `log_level: "DEBUG"`
3. Check metrics for anomalies
4. File an issue with logs and configuration

## Version History

- **v1.0.0** (2025-10-28): Initial release
  - Client detection with caching
  - Core tool translation
  - MCP bridge support
  - Comprehensive configuration
  - Telemetry and monitoring
