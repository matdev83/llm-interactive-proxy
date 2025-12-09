# Inline Python Steering

Prevent unstable inline Python execution by steering agents toward script-based execution.

## Overview

The Inline Python Steering feature intercepts attempts to run inline Python code via shell commands (e.g., `python -c "..."`) and guides the agent to use temporary scripts instead. Inline Python code execution in terminals is often unstable, prone to quoting issues, and difficult to debug. By enforcing script usage, this feature improves reliability and maintainability of agent-generated code execution.

When an agent attempts to execute inline Python, the proxy blocks the call and returns a steering message explaining the issue and suggesting the creation of a temporary script.

## Key Features

- **Automatic Detection**: Recognizes various inline Python patterns (`python -c`, `python3 -c`, etc.)
- **Immediate Blocking**: Prevents the command from executing on the host
- **Helpful Steering**: Explains why the command was blocked and what to do instead
- **Robust Parsing**: Handles various python executables and flags
- **Tool Awareness**: Monitors known shell execution tools

## Configuration

The feature is disabled by default and can be enabled via environment variable or YAML configuration.

### Environment Variable

```bash
export INLINE_PYTHON_STEERING_ENABLED=true
```

### YAML Configuration

```yaml
session:
  inline_python_steering_enabled: true  # Default: false
  
  # Optional: Custom steering message
  inline_python_steering_message: |
    Inline Python execution is blocked for stability reasons.
    Please write your code to a temporary file (e.g., script.py) and execute that file instead.
```

## Usage Examples

### Enable with Default Message

Set the environment variable before running the proxy:

```bash
export INLINE_PYTHON_STEERING_ENABLED=true
.venv/Scripts/python.exe -m src.core.cli --default-backend openai
```

### Enable with Custom Message

Create `config/my_config.yaml`:

```yaml
session:
  inline_python_steering_enabled: true
  inline_python_steering_message: |
    [Security/Stability Notice]
    You are attempting to run inline Python code (python -c).
    This pattern is unreliable in this environment.
    
    Please:
    1. Create a file named 'temp_script.py' with your code
    2. Run 'python temp_script.py'
```

Then run:

```bash
.venv/Scripts/python.exe -m src.core.cli --config config/my_config.yaml
```

## Detection Logic

The handler detects commands matching the following patterns:

- `python -c "..."`
- `python3 -c '...'`
- `python.exe -c "..."`
- `python -u -c "..."` (with flags)

It specifically looks for the `-c` flag combined with a Python executable. Normal Python file execution (e.g., `python script.py` or `python -m pytest`) is **allowed**.

## Recognized Shell Tools

The handler monitors the following shell execution tools (from `ShellExecutionTools` constant):

- `bash`
- `Execute`
- `ShellTool`
- `exec_command`
- `execute_command`
- `run_shell_command`
- `run_terminal_command`
- `shell`
- `local_shell`
- `container.exec`

## Rationale

Why block inline Python?

1.  **Quoting Hell**: Passing complex Python code inside shell strings often leads to escaping issues, especially on Windows (cmd.exe vs PowerShell) and with nested quotes.
2.  **Terminal Stability**: Long or complex inline one-liners can behave unpredictably depending on the underlying shell.
3.  **Debuggability**: Code in a file is easier to review, debug, and log than a ephemeral one-liner.
4.  **Agent Behavior**: Encouraging agents to write scripts fosters better coding habits and more robust solutions.

## Behavior Flow

1.  **Agent Action**: Agent calls a shell tool with `python -c "print('hello')"`
2.  **Interception**: The `InlinePythonSteeringHandler` detects the pattern.
3.  **Blocking**: The tool call is swallow (not executed).
4.  **Response**: The agent receives the steering message (default or custom).
5.  **Correction**: The agent should then create a file and execute it, which is allowed.

## Troubleshooting

**Feature not working:**
- Verify `INLINE_PYTHON_STEERING_ENABLED` is set to `true`.
- Ensure the tool being used is one of the recognized shell tools.

**False Positives:**
- The regex is designed to be specific to `-c`. If you find valid commands being blocked, please report them.
- Normal `python filename.py` should never be blocked.

## Implementation References

- **Handler**: `src/core/services/tool_call_handlers/inline_python_steering_handler.py`
- **Tests**: `tests/unit/core/services/tool_call_handlers/test_inline_python_steering_handler.py`
- **Configuration**: `src/core/config/app_config.py`
- **DI Registration**: `src/core/di/services.py`
