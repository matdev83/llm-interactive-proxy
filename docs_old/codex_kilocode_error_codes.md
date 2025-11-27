# Codex-KiloCode Compatibility Layer Error Codes

## Overview

This document provides a comprehensive reference for all error codes emitted by the Codex-KiloCode compatibility layer, along with troubleshooting steps and solutions.

## Error Code Format

Error codes follow the format: `COMPAT_E###`

- `COMPAT`: Indicates compatibility layer error
- `E`: Error type
- `###`: Unique error number

## Error Codes

### COMPAT_E001: Unsupported Tool

**Description**: The KiloCode client requested a tool that is not supported by the compatibility layer.

**Common Causes**:
- Client using browser automation tools (`<browser_action>`)
- Client using screenshot tools (`<screenshot>`)
- Client using tools not in the supported list
- Tool disabled in configuration

**Error Message Example**:
```json
{
  "error": true,
  "error_code": "COMPAT_E001",
  "message": "Unsupported tool: <browser_action>",
  "details": {
    "tool_name": "browser_action",
    "original_xml": "<browser_action>...</browser_action>",
    "supported_tools": ["read_file", "list_files", "execute_command", "..."],
    "suggestion": "Use codebase_search for finding code patterns"
  }
}
```

**Troubleshooting Steps**:

1. **Check Supported Tools List**
   ```yaml
   # In config/backends/openai_codex/backend.yaml
   compatibility_layer:
     translation:
       tools:
         browser_action: false  # Not supported
   ```

2. **Enable Tool if Available**
   ```yaml
   compatibility_layer:
     translation:
       tools:
         read_file: true  # Enable if disabled
   ```

3. **Use Alternative Tool**
   - Instead of `<browser_action>`, use `<codebase_search>`
   - Instead of `<screenshot>`, describe the UI in text

4. **Check Configuration**
   ```bash
   # Verify tool is enabled
   grep -A 20 "tools:" config/backends/openai_codex/backend.yaml
   ```

**Resolution**:
- Use a supported tool from the list
- Enable the tool in configuration if it's supported but disabled
- Update KiloCode client to use alternative tools

---

### COMPAT_E002: Invalid XML Syntax

**Description**: The XML tool invocation has malformed syntax and cannot be parsed.

**Common Causes**:
- Missing closing tags
- Unescaped special characters
- Nested tags not properly closed
- Invalid XML structure

**Error Message Example**:
```json
{
  "error": true,
  "error_code": "COMPAT_E002",
  "message": "Invalid XML syntax in tool invocation",
  "details": {
    "original_xml": "<read_file>src/main.py",
    "parse_error": "Missing closing tag for 'read_file'",
    "line": 1,
    "column": 25
  }
}
```

**Troubleshooting Steps**:

1. **Validate XML Structure**
   ```xml
   <!-- Incorrect -->
   <read_file>src/main.py
   
   <!-- Correct -->
   <read_file>src/main.py</read_file>
   ```

2. **Escape Special Characters**
   ```xml
   <!-- Incorrect -->
   <execute_command>echo "Hello & Goodbye"</execute_command>
   
   <!-- Correct -->
   <execute_command>echo "Hello &amp; Goodbye"</execute_command>
   ```

3. **Check Nested Tags**
   ```xml
   <!-- Incorrect -->
   <use_mcp_tool>
     <tool_name>patch_file
     <arguments>...</arguments>
   </use_mcp_tool>
   
   <!-- Correct -->
   <use_mcp_tool>
     <tool_name>patch_file</tool_name>
     <arguments>...</arguments>
   </use_mcp_tool>
   ```

4. **Enable Detailed Logging**
   ```yaml
   telemetry:
     log_level: "DEBUG"
     include_xml_in_errors: true
   ```

**Resolution**:
- Fix XML syntax errors
- Escape special characters (`&`, `<`, `>`, `"`, `'`)
- Ensure all tags are properly closed
- Validate XML before sending

---

### COMPAT_E003: Parameter Validation Failed

**Description**: Tool parameters failed validation (missing required parameters, invalid types, or out-of-range values).

**Common Causes**:
- Missing required parameters
- Wrong parameter types (string instead of integer)
- Values outside acceptable ranges
- Invalid file paths or patterns

**Error Message Example**:
```json
{
  "error": true,
  "error_code": "COMPAT_E003",
  "message": "Parameter validation failed for tool 'read_file'",
  "details": {
    "tool_name": "read_file",
    "parameter": "path",
    "validation_error": "Path must be relative to workspace",
    "provided_value": "/etc/passwd",
    "expected": "Relative path within workspace"
  }
}
```

**Troubleshooting Steps**:

1. **Check Required Parameters**
   ```xml
   <!-- Incorrect: missing path -->
   <read_file></read_file>
   
   <!-- Correct -->
   <read_file>src/main.py</read_file>
   ```

2. **Validate Parameter Types**
   ```xml
   <!-- Incorrect: recursive should be boolean -->
   <list_files>
     <path>src</path>
     <recursive>yes</recursive>
   </list_files>
   
   <!-- Correct -->
   <list_files>
     <path>src</path>
     <recursive>true</recursive>
   </list_files>
   ```

3. **Check Path Restrictions**
   ```yaml
   # In configuration
   translation:
     file_operations:
       restrict_to_workspace: true  # Paths must be relative
   ```

4. **Verify File Size Limits**
   ```yaml
   translation:
     file_operations:
       max_file_size: 10485760  # 10 MB limit
   ```

**Resolution**:
- Provide all required parameters
- Use correct parameter types
- Ensure paths are relative to workspace
- Check file size limits

---

### COMPAT_E004: Tool Execution Failed

**Description**: Tool execution failed during proxy-side execution.

**Common Causes**:
- File not found
- Permission denied
- Command execution failed
- Timeout exceeded
- Resource exhaustion

**Error Message Example**:
```json
{
  "error": true,
  "error_code": "COMPAT_E004",
  "message": "Tool execution failed: read_file",
  "details": {
    "tool_name": "read_file",
    "execution_error": "File not found: src/missing.py",
    "exit_code": 1,
    "stderr": "No such file or directory"
  }
}
```

**Troubleshooting Steps**:

1. **Check File Exists**
   ```bash
   # Verify file exists
   ls -la src/main.py
   ```

2. **Check Permissions**
   ```bash
   # Verify read permissions
   ls -l src/main.py
   chmod 644 src/main.py
   ```

3. **Check Timeout Settings**
   ```yaml
   translation:
     max_tool_execution_timeout: 30  # Increase if needed
   ```

4. **Check Command Execution**
   ```bash
   # Test command manually
   bash -c "echo 'test'"
   ```

5. **Review Logs**
   ```yaml
   telemetry:
     log_level: "DEBUG"
     log_translations: true
   ```

**Resolution**:
- Verify file/directory exists
- Check file permissions
- Increase timeout if needed
- Fix command syntax
- Check disk space and resources

---

### COMPAT_E005: MCP Bridge Error

**Description**: Error occurred while bridging to MCP server.

**Common Causes**:
- MCP server not available
- MCP tool not found
- Schema translation failed
- MCP server returned error

**Error Message Example**:
```json
{
  "error": true,
  "error_code": "COMPAT_E005",
  "message": "MCP bridge error: Tool not found",
  "details": {
    "mcp_tool": "custom_analyzer",
    "mcp_server": "code-analysis-server",
    "error": "Tool 'custom_analyzer' not registered",
    "available_tools": ["lint", "format", "analyze"]
  }
}
```

**Troubleshooting Steps**:

1. **Check MCP Server Status**
   ```bash
   # Verify MCP server is running
   curl http://localhost:8080/health
   ```

2. **List Available Tools**
   ```bash
   # Query MCP server for tools
   curl http://localhost:8080/tools
   ```

3. **Check MCP Configuration**
   ```yaml
   # In main config
   mcp:
     servers:
       code-analysis-server:
         url: "http://localhost:8080"
         timeout: 30
   ```

4. **Test MCP Tool Directly**
   ```bash
   # Test MCP tool
   curl -X POST http://localhost:8080/tools/lint \
     -H "Content-Type: application/json" \
     -d '{"file": "src/main.py"}'
   ```

**Resolution**:
- Start MCP server if not running
- Use correct tool name from available tools
- Check MCP server configuration
- Verify network connectivity to MCP server

---

### COMPAT_E006: Detection Failed

**Description**: Client detection failed or produced ambiguous results.

**Common Causes**:
- No detection method succeeded
- Conflicting detection results
- Invalid agent metadata
- Corrupted request data

**Error Message Example**:
```json
{
  "error": true,
  "error_code": "COMPAT_E006",
  "message": "Client detection failed",
  "details": {
    "attempted_methods": ["metadata", "header", "heuristic"],
    "results": {
      "metadata": "not_found",
      "header": "not_found",
      "heuristic": "insufficient_evidence"
    },
    "suggestion": "Ensure client sends agent metadata or User-Agent header"
  }
}
```

**Troubleshooting Steps**:

1. **Check Agent Metadata**
   ```python
   # Client should send
   {
     "agent": "kilocode",
     "version": "1.0.0"
   }
   ```

2. **Check User-Agent Header**
   ```http
   User-Agent: KiloCode/1.0.0
   ```

3. **Enable Heuristic Detection**
   ```yaml
   detection:
     methods:
       heuristic: true
     heuristic_threshold: 2
   ```

4. **Check Detection Logs**
   ```yaml
   telemetry:
     log_detection: true
     log_level: "DEBUG"
   ```

**Resolution**:
- Add agent metadata to requests
- Set User-Agent header
- Enable heuristic detection
- Lower heuristic threshold

---

### COMPAT_E007: Translation Timeout

**Description**: Tool translation or execution exceeded the configured timeout.

**Common Causes**:
- Long-running command execution
- Large file operations
- Slow MCP server response
- Network latency

**Error Message Example**:
```json
{
  "error": true,
  "error_code": "COMPAT_E007",
  "message": "Translation timeout exceeded",
  "details": {
    "tool_name": "execute_command",
    "timeout_seconds": 30,
    "elapsed_seconds": 31,
    "suggestion": "Increase max_tool_execution_timeout or optimize command"
  }
}
```

**Troubleshooting Steps**:

1. **Increase Timeout**
   ```yaml
   translation:
     max_tool_execution_timeout: 60  # Increase from 30 to 60
   ```

2. **Optimize Command**
   ```bash
   # Instead of
   find / -name "*.py"
   
   # Use
   find . -name "*.py"  # Search current directory only
   ```

3. **Check System Load**
   ```bash
   # Check CPU and memory
   top
   htop
   ```

4. **Profile Execution Time**
   ```yaml
   telemetry:
     log_translations: true
     log_level: "DEBUG"
   ```

**Resolution**:
- Increase timeout configuration
- Optimize long-running operations
- Check system resources
- Use more efficient commands

---

## Diagnostic Procedures

### Enable Debug Logging

```yaml
# In config/backends/openai_codex/backend.yaml
compatibility_layer:
  telemetry:
    log_level: "DEBUG"
    log_translations: true
    log_detection: true
    include_xml_in_errors: true
```

### Check Metrics

```bash
# Query Prometheus metrics
curl http://localhost:8000/metrics | grep compatibility_layer

# Check error rates
compatibility_layer_error_total{error_code="COMPAT_E001"} 5
compatibility_layer_error_total{error_code="COMPAT_E004"} 2
```

### Review Logs

```bash
# Search for compatibility layer errors
grep "COMPAT_E" logs/proxy.log

# Filter by error code
grep "COMPAT_E001" logs/proxy.log

# Show context around errors
grep -A 5 -B 5 "COMPAT_E" logs/proxy.log
```

### Test Configuration

```python
# Validate configuration
from src.connectors.openai_codex_config import load_and_validate_config

config, errors = load_and_validate_config("config/backends/openai_codex/backend.yaml")
if errors:
    print("Configuration errors:")
    for error in errors:
        print(f"  - {error}")
else:
    print("Configuration is valid")
```

## Common Troubleshooting Workflows

### Workflow 1: Tool Not Working

1. Check if tool is supported (see supported tools list)
2. Verify tool is enabled in configuration
3. Check XML syntax is correct
4. Review error logs for specific error code
5. Test tool manually if possible
6. Check permissions and file access

### Workflow 2: Performance Issues

1. Check detection cache hit rate
2. Review translation latency metrics
3. Profile tool execution times
4. Check system resources (CPU, memory, disk)
5. Optimize long-running operations
6. Increase timeouts if necessary

### Workflow 3: Configuration Issues

1. Validate configuration syntax (YAML)
2. Run configuration validation script
3. Check for typos in option names
4. Verify values are within acceptable ranges
5. Review configuration documentation
6. Test with minimal configuration first

### Workflow 4: Integration Issues

1. Verify Codex backend is accessible
2. Check API key is valid
3. Test with non-KiloCode client
4. Review detection logs
5. Check prompt preservation
6. Verify tool translation is working

## Prevention Best Practices

### 1. Configuration Validation

Always validate configuration before deployment:

```bash
python -c "
from src.connectors.openai_codex_config import load_and_validate_config
config, errors = load_and_validate_config('config/backends/openai_codex/backend.yaml')
if errors:
    print('Errors:', errors)
    exit(1)
"
```

### 2. Monitoring and Alerts

Set up alerts for:
- Error rate > 5% (any error code)
- Translation latency > 100ms (p95)
- Detection failures > 1% of requests
- Tool execution timeouts > 2% of executions

### 3. Testing

Test compatibility layer with:
- Unit tests for each tool translation
- Integration tests for end-to-end flows
- Load tests for performance validation
- Regression tests for known issues

### 4. Gradual Rollout

Roll out compatibility layer gradually:
1. Enable for test environment
2. Monitor for 24 hours
3. Enable for 10% of production traffic
4. Monitor for 48 hours
5. Gradually increase to 100%

### 5. Rollback Plan

Always have a rollback plan:
```yaml
# Quick disable
compatibility_layer:
  enabled: false
```

Keep previous configuration backed up:
```bash
cp config/backends/openai_codex/backend.yaml \
   config/backends/openai_codex/backend.yaml.backup
```

## Getting Help

If you encounter an error not covered in this document:

1. **Check Logs**: Review logs with DEBUG level enabled
2. **Check Metrics**: Look for anomalies in metrics
3. **Search Issues**: Search existing issues for similar problems
4. **File Issue**: Create new issue with:
   - Error code and message
   - Configuration (sanitized)
   - Logs (relevant sections)
   - Steps to reproduce
   - Expected vs actual behavior

## Appendix: Error Code Quick Reference

| Code | Description | Common Cause | Quick Fix |
|------|-------------|--------------|-----------|
| E001 | Unsupported Tool | Tool not in supported list | Use alternative tool |
| E002 | Invalid XML | Malformed XML syntax | Fix XML syntax |
| E003 | Parameter Validation | Invalid parameters | Check parameter types/values |
| E004 | Execution Failed | File not found, permission denied | Check file exists and permissions |
| E005 | MCP Bridge Error | MCP server unavailable | Start MCP server |
| E006 | Detection Failed | No detection method succeeded | Add agent metadata |
| E007 | Translation Timeout | Operation took too long | Increase timeout |
