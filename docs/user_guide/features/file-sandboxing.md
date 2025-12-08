# File Access Sandboxing

## Overview

File access sandboxing is a security feature that restricts LLM agents from performing file-changing operations outside of the detected project root directory. This prevents agents from accidentally or maliciously modifying files in sensitive system locations.

---

## Quick Start

### Enable via CLI Flag

```bash
./.venv/Scripts/python.exe -m src.core.cli --enable-sandboxing
```

### Enable via Environment Variable

```bash
# Windows PowerShell
$env:ENABLE_SANDBOXING="true"
./.venv/Scripts/python.exe -m src.core.cli

# Windows CMD
set ENABLE_SANDBOXING=true
.venv\Scripts\python.exe -m src.core.cli

# Linux/Mac
export ENABLE_SANDBOXING=true
python -m src.core.cli
```

### Enable via YAML Configuration

Create or edit `config/config.yaml`:

```yaml
sandboxing:
  enabled: true
  strict_mode: false
  allow_parent_access: false
```

---

## Configuration Options

### Basic Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable/disable file access sandboxing |
| `strict_mode` | boolean | `false` | Block tool calls with unparseable file paths |
| `allow_parent_access` | boolean | `false` | Allow access to parent directories of project root |

### Advanced Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `custom_tool_patterns` | list[string] | `[]` | Additional regex patterns for file-changing tools |
| `excluded_tools` | list[string] | `[]` | Regex patterns for tools to exempt from sandboxing |
| `path_parameter_names` | list[string] | See below | Parameter names that may contain file paths |
| `default_tool_patterns` | list[string] | See below | Built-in patterns for file-changing tools |

---

## How It Works

### 1. Project Root Detection

The proxy automatically detects the project root by looking for common markers:
- `.git` directory
- `pyproject.toml`
- `package.json`
- Other version control or build system files

### 2. Tool Call Interception

When enabled, the sandboxing handler intercepts tool calls that match file-changing patterns:
- `write_to_file`, `write_file`, `fsWrite`
- `edit_file`, `patch_file`, `apply_diff`
- `delete_file`, `remove_file`
- `create_file`, `move_file`, `rename_file`, `copy_file`
- `str_replace`, `replace_in_file`
- And more (see default_tool_patterns)

### 3. Path Validation

For each intercepted tool call:
1. Extract file paths from tool arguments (checks `path`, `file_path`, `target`, etc.)
2. Resolve paths to absolute paths
3. Check if the path is within the project root boundary
4. Block the call if it's outside the boundary (unless `allow_parent_access` is enabled)

### 4. Blocking Behavior

When a violation is detected:
```json
{
  "should_swallow": true,
  "error_to_model": "File sandboxing violation: Path '/etc/passwd' is outside project directory '/home/user/myproject'. Operation blocked for security.",
  "metadata": {
    "decision": "blocked",
    "path": "/etc/passwd",
    "project_root": "/home/user/myproject"
  }
}
```

The model receives an error message and can adjust its behavior.

---

## Configuration Examples

### Basic Protection (Recommended)

```yaml
sandboxing:
  enabled: true
  strict_mode: false
  allow_parent_access: false
```

**Use case**: Basic protection for development environments where you want to prevent accidental modifications outside the project.

### Strict Mode

```yaml
sandboxing:
  enabled: true
  strict_mode: true
  allow_parent_access: false
```

**Use case**: Maximum security. Blocks any tool call with unparseable paths. Recommended for production or untrusted agents.

### Allow Parent Access

```yaml
sandboxing:
  enabled: true
  strict_mode: false
  allow_parent_access: true
```

**Use case**: When your project needs to access files in parent directories (e.g., monorepo structure).

### Custom Tool Patterns

```yaml
sandboxing:
  enabled: true
  custom_tool_patterns:
    - "my_custom_write_tool"
    - "save_.*_to_disk"
  excluded_tools:
    - "read_only_tool"
    - "safe_.*_viewer"
```

**Use case**: Add custom file-changing tools or exclude specific read-only tools from sandboxing.

### Custom Path Parameters

```yaml
sandboxing:
  enabled: true
  path_parameter_names:
    - "path"
    - "file_path"
    - "my_custom_path_param"
```

**Use case**: When your tools use non-standard parameter names for file paths.

---

## Default Patterns

### Default Tool Patterns

The following tool name patterns are checked by default:
```python
[
    "write_to_file", "write_file", "fsWrite",
    "replace_in_file", "str_replace", "strReplace",
    "edit_file", "patch_file", "apply_diff", "apply_patch",
    "delete_file", "deleteFile", "remove_file",
    "create_file", "move_file", "rename_file", "copy_file",
    "insert_content", "search_and_replace",
    "generate_image"
]
```

### Default Path Parameter Names

The following parameter names are checked for file paths:
```python
[
    "path", "file_path", "filepath", "file",
    "target", "target_file", "destination", "dest",
    "source", "src", "fileName", "filePath",
    "image", "patch", "diff",
    "paths", "files", "file_list", "targets"
]
```

---

## CLI Priority

The CLI flag has the highest priority and overrides both environment variables and YAML configuration:

1. **CLI Flag** (highest priority): `--enable-sandboxing`
2. **Environment Variable**: `ENABLE_SANDBOXING=true`
3. **YAML Configuration** (lowest priority): `sandboxing.enabled: true`

---

## Testing

To verify sandboxing is working:

```bash
# Start proxy with sandboxing enabled
./.venv/Scripts/python.exe -m src.core.cli --enable-sandboxing

# In another terminal, send a test request that tries to write outside project
# The proxy should block the operation and return an error to the model
```

Check logs for:
```
[INFO] File sandboxing handler initialized with project root: /path/to/project
[INFO] File sandboxing violation detected for tool 'write_file'
```

---

## Troubleshooting

### Sandboxing Not Working?

1. **Check if enabled**:
   ```bash
   # Look for this in startup logs
   [INFO] File sandboxing handler initialized
   ```

2. **Verify project root detection**:
   ```bash
   # Check startup logs for detected project root
   [INFO] Project root detected: /path/to/project
   ```

3. **Check tool names**:
   - Tool names must match the regex patterns
   - Add custom patterns if your agent uses different tool names

### False Positives?

If legitimate operations are being blocked:

1. **Use `excluded_tools`** to exempt specific tools:
   ```yaml
   sandboxing:
     enabled: true
     excluded_tools:
       - "read_only_tool"
   ```

2. **Enable `allow_parent_access`** if you need parent directory access:
   ```yaml
   sandboxing:
     enabled: true
     allow_parent_access: true
   ```

### False Negatives?

If some file operations are not being caught:

1. **Add custom patterns** for your tools:
   ```yaml
   sandboxing:
     enabled: true
     custom_tool_patterns:
       - "my_custom_write_tool"
   ```

2. **Add custom path parameter names**:
   ```yaml
   sandboxing:
     enabled: true
     path_parameter_names:
       - "path"
       - "my_custom_path_param"
   ```

---

## Security Considerations

### What It Protects Against

✅ Accidental file modifications outside project  
✅ Agent mistakes (writing to wrong directory)  
✅ Basic malicious attempts to access system files  

### What It Does NOT Protect Against

❌ **Sophisticated attacks** - Determined attackers can potentially bypass path validation  
❌ **Command injection** - Sandboxing only checks file paths, not command execution  
❌ **Read operations** - Only file-changing operations are blocked  
❌ **Network operations** - No network sandboxing  

### Best Practices

1. ⚠️ **Always use `strict_mode` in production**
2. ⚠️ **Never enable sandboxing as a substitute for proper system security**
3. ⚠️ **Review blocked operations in logs regularly**
4. ⚠️ **Test thoroughly before deploying with sandboxing enabled**
5. ⚠️ **Use in combination with other security measures** (user permissions, containers, etc.)

---

## Performance Impact

File sandboxing has minimal performance impact:
- **Latency**: <1ms per tool call
- **Memory**: Negligible (path validation is lightweight)
- **CPU**: Minimal (regex matching only)

Priority level: **80** (runs before most handlers, after authentication)

---

## Related Documentation

- [Tool Call Reactor System](./tool-call-reactor.md)
- [Security Best Practices](../security/best-practices.md)
- [Configuration Guide](../configuration.md)
- [CLI Parameters](../cli-parameters.md)

---

## Example: Full Configuration

```yaml
# config/config.yaml
sandboxing:
  # Enable sandboxing
  enabled: true
  
  # Block unparseable paths
  strict_mode: true
  
  # Don't allow parent directory access
  allow_parent_access: false
  
  # Add custom file-changing tools
  custom_tool_patterns:
    - "my_save_tool"
    - "custom_write_.*"
  
  # Exempt read-only tools
  excluded_tools:
    - "read_file"
    - "list_directory"
  
  # Custom path parameter names (optional - defaults are usually sufficient)
  path_parameter_names:
    - "path"
    - "file_path"
    - "my_custom_path"
```

Start with:
```bash
./.venv/Scripts/python.exe -m src.core.cli
```

The CLI flag can override the config:
```bash
# Disable even if config says enabled
./.venv/Scripts/python.exe -m src.core.cli --enable-sandboxing=false
```
