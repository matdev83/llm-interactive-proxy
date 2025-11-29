# Codex-KiloCode Compatibility Layer

## Overview

The Codex-KiloCode Compatibility Layer is a translation subsystem within the LLM Interactive Proxy that enables seamless communication between KiloCode clients and the OpenAI Codex backend. It translates KiloCode's XML-style tool invocations into Codex-compatible format while preserving Codex's canonical system instructions.

## Documentation Index

### Getting Started
- **[Quick Start Guide](./codex_kilocode_quickstart.md)** - 5-minute setup guide
- **[Full Documentation](./codex_kilocode_compatibility.md)** - Complete operator guide

### Reference
- **[Supported Tools](./codex_kilocode_tools.md)** - Tool reference with examples
- **[Error Codes](./codex_kilocode_error_codes.md)** - Troubleshooting guide

### Configuration
- **Backend Config**: `config/backends/openai_codex/backend.yaml`
- **Config Schema**: `config/schemas/openai_codex_backend.schema.yaml`
- **Validation**: `src/connectors/openai_codex_config.py`

## Key Features

✅ **Automatic Client Detection** - Identifies KiloCode clients using metadata, headers, and heuristics
✅ **Tool Translation** - Converts 14 KiloCode XML tools to Codex format
✅ **Prompt Preservation** - Maintains Codex's canonical instructions byte-for-byte
✅ **Zero Impact** - No performance overhead for non-KiloCode clients
✅ **Highly Configurable** - Extensive security and behavior options
✅ **Observable** - Comprehensive telemetry and logging
✅ **Secure** - File access restrictions, command execution limits, input validation

## Quick Start

### 1. Create Configuration

```yaml
# config/backends/openai_codex/backend.yaml
backend_type: "openai-codex"
compatibility_layer:
  enabled: true
```

### 2. Set API Key

```bash
export OPENAI_API_KEY="your-api-key-here"
```

### 3. Restart Proxy

```bash
python -m src.core.cli
```

### 4. Verify

Check logs for: `INFO: Codex-Kilo compatibility layer activated`

## Supported Tools

### File Operations (5 tools)
- `read_file` - Read file contents
- `list_files` - List directory contents
- `write_to_file` - Write content to file
- `insert_content` - Insert content at position
- `edit_file` - Edit file with instructions

### Search Operations (2 tools)
- `codebase_search` - Search entire codebase
- `search_files` - Search with glob patterns

### Command Execution (1 tool)
- `execute_command` - Execute shell commands

### Editing Operations (2 tools)
- `search_and_replace` - Search and replace in files
- `use_mcp_tool` (patch_file) - Apply patches

### MCP Integration (2 tools)
- `access_mcp_resource` - Access MCP resources
- `use_mcp_tool` - Generic MCP tool invocation

### Conversation Control (2 tools)
- `attempt_completion` - Mark task complete
- `ask_followup_question` - Ask follow-up question

**Total: 14 supported tools**

## Architecture

```
KiloCode Client
    ↓ (XML tool invocations)
Session Detector
    ↓ (detect & cache)
Tool Translator
    ↓ (translate XML → Codex format)
Codex Backend
    ↓ (execute & respond)
Result Formatter
    ↓ (format for KiloCode)
KiloCode Client
```

## Configuration Options

### Global Settings
- `enabled` - Enable/disable compatibility layer

### Detection Settings
- `cache_ttl_seconds` - Cache TTL (default: 3600)
- `heuristic_threshold` - Min XML tags for detection (default: 2)
- `methods` - Enable/disable detection methods

### Translation Settings
- `max_tool_execution_timeout` - Tool timeout (default: 30s)
- `result_format` - Result format (default: kilo_standard)
- `tools` - Enable/disable specific tools

### Security Settings
- `command_execution.allowed_shells` - Allowed shells
- `command_execution.restrict_to_workspace` - Workspace restriction
- `file_operations.restrict_to_workspace` - File access restriction
- `file_operations.blocked_patterns` - Blocked file patterns

### Telemetry Settings
- `log_translations` - Log translation events
- `log_detection` - Log detection events
- `emit_metrics` - Emit Prometheus metrics
- `log_level` - Log level (DEBUG, INFO, WARNING, ERROR)

### Error Handling Settings
- `detailed_errors` - Return detailed error messages
- `include_suggestions` - Include suggestions in errors
- `fail_fast` - Stop on first error

## Error Codes

| Code | Description | Common Fix |
|------|-------------|------------|
| E001 | Unsupported tool | Use alternative tool |
| E002 | Invalid XML syntax | Fix XML syntax |
| E003 | Parameter validation failed | Check parameter types |
| E004 | Tool execution failed | Check file exists |
| E005 | MCP bridge error | Start MCP server |
| E006 | Detection failed | Add agent metadata |
| E007 | Translation timeout | Increase timeout |

## Monitoring

### Metrics

```
# Detection metrics
compatibility_layer_detection_total
compatibility_layer_detection_duration_seconds
compatibility_layer_cache_hit_total

# Translation metrics
compatibility_layer_translation_total
compatibility_layer_translation_duration_seconds
compatibility_layer_tool_execution_total

# Error metrics
compatibility_layer_error_total
compatibility_layer_unsupported_tool_total
```

### Logging

```bash
# Enable debug logging
telemetry:
  log_level: "DEBUG"
  log_translations: true
  log_detection: true

# View logs
tail -f logs/proxy.log | grep compatibility
```

## Security Best Practices

### 1. Restrict File Access
```yaml
file_operations:
  restrict_to_workspace: true
  blocked_patterns:
    - "**/.env*"
    - "**/*.key"
```

### 2. Limit Command Execution
```yaml
command_execution:
  allowed_shells: ["bash", "sh"]
  restrict_to_workspace: true
```

### 3. Disable Sensitive Tools
```yaml
tools:
  execute_command: false
  write_to_file: false
```

### 4. Monitor for Abuse
```yaml
telemetry:
  emit_metrics: true
  log_translations: true
```

## Performance

### Latency Targets
- Detection: <5ms (first request only, cached thereafter)
- Translation: <50ms per tool invocation
- Cache hit: <1ms

### Optimization Tips
1. Enable detection caching (default: enabled)
2. Reduce tool execution timeout for faster failures
3. Disable verbose logging in production
4. Use specific file paths instead of recursive searches

## Known Limitations

### Unsupported Tools
- `browser_action` - Browser automation not supported
- `screenshot` - Image capture not supported
- `inspect_site` - Web scraping not supported

### Codex Constraints
- Limited context window (8K tokens)
- Canonical instructions cannot be modified
- Some MCP tools may not be supported

### Performance Considerations
- Large files may be truncated
- Long-running commands may timeout
- Recursive searches may be slow

## Troubleshooting

### Compatibility layer not activating
1. Check `enabled: true` in config
2. Verify client sends agent metadata
3. Enable heuristic detection

### Tool not working
1. Check tool is in supported list
2. Verify tool is enabled in config
3. Validate XML syntax

### Performance issues
1. Check detection cache is working
2. Reduce tool execution timeout
3. Disable verbose logging

### Permission errors
1. Check file/directory permissions
2. Verify workspace restrictions
3. Review blocked patterns

## Migration Guide

### From Direct Codex Integration
1. Backup current configuration
2. Create backend configuration
3. Enable compatibility layer
4. Test with KiloCode client
5. Monitor logs and metrics

### From Other Backends
1. Update default_backend to openai-codex
2. Configure compatibility layer
3. Test all tools
4. Adjust timeouts
5. Monitor costs

## Development

### Configuration Validation

```python
from src.connectors.openai_codex_config import load_and_validate_config

config, errors = load_and_validate_config("config/backends/openai_codex/backend.yaml")
if errors:
    print("Configuration errors:", errors)
else:
    print("Configuration is valid")
```

### Testing

```bash
# Run unit tests
pytest tests/unit/test_openai_codex_config.py

# Run integration tests
pytest tests/integration/test_codex_kilocode_compatibility.py

# Run all compatibility layer tests
pytest -k "codex_kilocode"
```

## Support

### Documentation
- [Quick Start](./codex_kilocode_quickstart.md)
- [Full Guide](./codex_kilocode_compatibility.md)
- [Tool Reference](./codex_kilocode_tools.md)
- [Error Codes](./codex_kilocode_error_codes.md)

### Debugging
1. Enable DEBUG logging
2. Check metrics for anomalies
3. Review error logs
4. Validate configuration

### Getting Help
1. Check documentation
2. Review logs with DEBUG level
3. Check metrics endpoint
4. File issue with logs and config

## Version History

### v1.0.0 (2025-10-28)
- Initial release
- 14 supported tools
- Client detection with caching
- Tool translation (XML → Codex)
- MCP bridge support
- Comprehensive configuration
- Telemetry and monitoring
- Security restrictions
- Complete documentation

## License

See main project LICENSE file.

## Contributing

See main project CONTRIBUTING.md file.

## Acknowledgments

- OpenAI Codex team for the backend API
- KiloCode team for the client implementation
- LLM Interactive Proxy contributors

---

**Quick Links:**
- [Quick Start](./codex_kilocode_quickstart.md) - Get started in 5 minutes
- [Configuration](./codex_kilocode_compatibility.md#configuration-options) - All configuration options
- [Tools](./codex_kilocode_tools.md) - Supported tools reference
- [Errors](./codex_kilocode_error_codes.md) - Error codes and troubleshooting
- [Schema](../config/schemas/openai_codex_backend.schema.yaml) - Configuration schema
