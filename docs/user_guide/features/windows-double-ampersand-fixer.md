# Windows Double-Ampersand Command Fixer

The proxy includes automatic on-the-fly rewriting of `&&` (double ampersand) command separators for Windows clients. Remote LLMs are predominantly trained on Linux workflows and frequently generate shell commands using `&&` as a command separator, which fails on Windows PowerShell.

## Overview

This feature transparently intercepts tool calls to command execution tools, detects `&&` patterns in command arguments, and replaces them with ` ; ` (semicolon with spaces) before the tool call reaches the client agent. This happens on-the-fly without any additional round trips to the remote LLM.

## Key Features

- **Automatic Detection**: Detects when the client OS is Windows from session context
- **On-the-fly Replacement**: Modifies `&&` to ` ; ` in command arguments transparently
- **Tool Filtering**: Only modifies command execution tools, never file editing tools
- **Zero Round Trips**: Works inline without requiring additional LLM interactions
- **Configurable**: Can be disabled via CLI flag, environment variable, or config file

## How It Works

1. The proxy detects the client OS from request messages (e.g., "User system info (win32 10.0.19045)")
2. When a tool call response contains a command execution tool (e.g., `Execute`, `run_command`)
3. The proxy scans the command argument for `&&` patterns
4. All `&&` occurrences are replaced with ` ; `
5. The modified tool call is sent to the client

## Supported Command Execution Tools

The following tool names trigger the replacement logic:

- `execute`, `Execute`
- `run_command`, `run-command`
- `bash`, `shell`, `terminal`
- `exec`, `run`
- `execute_command`
- `cmd`, `powershell`, `command`
- `run_terminal_command`
- `execute_bash`, `run_shell`

## Protected Tools (Never Modified)

The following tool types are never modified to prevent data corruption:

- `write_file`, `Edit`, `Create`
- `str_replace`, `patch_file`, `apply_diff`
- `multiedit`, `insert_content`, `replace_lines`
- `read_file`, `grep`, `glob`, `ls`

## Configuration

The feature is **enabled by default**. Configuration follows precedence: CLI > Environment > Config File.

### CLI Flag

```bash
# Disable the feature
python -m src.core.cli --disable-double-ampersand-fixes-for-windows
```

### Environment Variable

```bash
# Disable the feature
export DOUBLE_AMPERSAND_FIXES_FOR_WINDOWS_ENABLED=false
```

### Config File

```yaml
# config.yaml
session:
  double_ampersand_fixes_for_windows_enabled: false
```

## Usage Examples

### Before and After

**Original command from LLM:**
```
cd /project && npm install && npm run build
```

**Modified command for Windows client:**
```
cd /project ; npm install ; npm run build
```

### Various Patterns

| Original | Modified |
|----------|----------|
| `cmd1 && cmd2` | `cmd1 ; cmd2` |
| `cmd1&&cmd2` | `cmd1 ; cmd2` |
| `cmd1  &&  cmd2` | `cmd1 ; cmd2` |
| `a && b && c && d` | `a ; b ; c ; d` |

## Logging

When a modification occurs, the proxy logs at INFO level:

```
Fixed double-ampersand in command for Windows client: tool=Execute, original='cd /project && npm install...', fixed='cd /project ; npm install...'
```

Debug-level logging shows when tool calls are checked but not modified.

## When to Disable

Only disable this feature if:

- Your Windows environment properly handles `&&` (some newer PowerShell versions may support it)
- You need the exact command syntax to be preserved for debugging
- You're using a tool that requires `&&` in its syntax

## Related Features

- [Dangerous Command Protection](dangerous-command-protection.md) - Blocks potentially destructive git commands
- [Tool Access Control](tool-access-control.md) - Fine-grained control over tool execution
