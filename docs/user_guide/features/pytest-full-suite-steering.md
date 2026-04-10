# Pytest Full-Suite Steering

Prevent agents from running entire test suites inadvertently by steering them toward targeted testing.

## Overview

The Pytest Full-Suite Steering feature monitors tool calls from LLMs and issues a steering message when they attempt to run the entire test suite without specifying specific tests. This helps prevent time-consuming full test suite runs when targeted testing would be more efficient.

When an agent tries to run `pytest` without arguments, the proxy intercepts the command, returns a helpful steering message, and remembers this attempt. If the agent re-issues the same command, the proxy allows it through, assuming the full suite is genuinely needed.

## Key Features

- **Automatic Detection**: Recognizes full-suite pytest commands across various formats
- **Smart Steering**: Blocks first attempt, allows second attempt (per session)
- **Session Isolation**: Each session has independent state
- **Configurable Messages**: Customize the steering message
- **Wrapper Recognition**: Detects pytest through pipenv, poetry, uv, etc.
- **Priority Handling**: Runs at priority 95 (after dangerous commands, before generic steering)

## Configuration

The feature is disabled by default and can be enabled via CLI flag, environment variable, or YAML configuration.

### Configuration Precedence

CLI > Environment Variable > YAML Configuration

### CLI Flag

```bash
--enable-pytest-full-suite-steering    # Enable the feature
--disable-pytest-full-suite-steering   # Explicitly disable
```

### Environment Variable

```bash
export PYTEST_FULL_SUITE_STEERING_ENABLED=true  # or false
```

### YAML Configuration

```yaml
session:
  pytest_full_suite_steering_enabled: true  # Default: false
  
  # Optional: Custom steering message
  pytest_full_suite_steering_message: |
    You requested to run the whole test suite. This may be a lengthy process.
    Please consider running only selected tests for optimal speed. If you still
    believe you need to run the whole test suite, please re-send your tool call
    and it will be executed.
```

## Usage Examples

### Enable with Default Message

```bash
.venv/Scripts/python.exe -m src.core.cli \
  --enable-pytest-full-suite-steering \
  --default-backend openai
```

### Enable with Custom Message

Create `config/my_config.yaml`:

```yaml
session:
  pytest_full_suite_steering_enabled: true
  pytest_full_suite_steering_message: |
    FULL TEST SUITE DETECTED
    
    You're about to run the entire test suite, which may take several minutes.
    
    Consider running specific tests instead:
    - pytest tests/unit/test_file.py
    - pytest tests/integration/
    - pytest -k "test_name_pattern"
    
    If you really need the full suite, re-send the same command.
```

Then run:

```bash
.venv/Scripts/python.exe -m src.core.cli --config config/my_config.yaml
```

### Enable via Environment Variable

```bash
export PYTEST_FULL_SUITE_STEERING_ENABLED=true
.venv/Scripts/python.exe -m src.core.cli --default-backend openai
```

## Detection Logic

### Full-Suite Commands (Swallowed on First Attempt)

The handler detects these as full-suite commands:

- `pytest` (no arguments)
- `python -m pytest`
- `py.test`
- `pytest .` (current directory)
- `pytest -q` (only flags, no file selectors)
- `pipenv run pytest`
- `poetry run pytest`
- `uv run pytest`

### Targeted Commands (Allowed Through Immediately)

These commands are recognized as targeted and pass through:

- `pytest tests/unit/test_file.py` (specific file)
- `pytest tests/` (specific directory)
- `pytest -k marker` (marker filtering)
- `pytest --lf` (last failed tests)
- `pytest tests/unit/test_file.py::TestClass::test_method` (node selection)

## Behavior Flow

### First Attempt

1. Agent sends tool call: `pytest`
2. Handler intercepts and swallows the command
3. Returns steering message instead of executing
4. Remembers this command for the current session

### Second Attempt

1. Agent re-issues the same command: `pytest`
2. Handler recognizes it's the second attempt
3. Allows the command to execute
4. Assumes the agent genuinely needs the full suite

### Different Session

1. New session starts
2. Agent sends tool call: `pytest`
3. Handler swallows it (independent session state)
4. Process repeats for this new session

## Recognized Shell Tools

The handler monitors these tool names for pytest commands:

- `bash`, `cmd`, `shell`
- `exec`, `exec_command`, `execute`, `execute_command`
- `run_command`, `run_shell_command`, `run_terminal_cmd`
- `powershell`, `pwsh`, `executepwsh`
- `python` (for `-m pytest` invocations)
- `terminal`, `local_shell`
- `container.exec`

## Command Extraction

The handler extracts commands from various argument formats:

- **String**: `"pytest"`
- **Dict with command**: `{"command": "pytest"}`
- **Dict with input**: `{"input": "pytest"}`
- **List/tuple**: `["pytest", "-q"]`
- **Nested structures**: `{"body": {"command": "pytest"}}`

## Session State Management

The handler maintains session state with:

- **TTL**: 1800 seconds (30 minutes) by default
- **Max Sessions**: 1024 sessions cached
- **Automatic Cleanup**: Expired sessions are pruned automatically

Each session tracks which full-suite commands have been attempted, ensuring the second attempt is allowed through.

## Use Cases

### Prevent Accidental Full-Suite Runs

During iterative development, agents may default to running the full test suite:

```bash
# Agent's first attempt
Agent: "Let me run pytest to check all tests"
Proxy: [Steering message suggesting targeted tests]

# Agent's second attempt (if needed)
Agent: "Run pytest"
Proxy: [Executes the full suite]
```

### Guide Toward Efficient Testing

The steering message educates agents about targeted testing:

```
Consider running specific tests instead:
- pytest tests/unit/test_file.py
- pytest tests/integration/
- pytest -k "test_name_pattern"
```

### Balance Control and Flexibility

The two-attempt mechanism provides:

- **First attempt**: Gentle steering toward efficiency
- **Second attempt**: Respects agent's judgment if full suite is needed

## Troubleshooting

**Feature not working:**

- Verify the feature is enabled (check config/env/CLI)
- Check logs for "Steering full-suite pytest command" messages
- Ensure the tool name is recognized (see "Recognized Shell Tools")
- Verify the command format matches detection patterns

**Commands not being detected:**

- Test the detection logic manually (see implementation)
- Check if the command includes file/directory selectors
- Verify the tool name is in the recognized list
- Review logs for parsing errors

**Steering message not appearing:**

- Confirm the feature is enabled in configuration
- Check that the command is recognized as full-suite
- Verify session state is being maintained
- Review handler registration in logs

**Second attempt not working:**

- Ensure the exact same command is being re-issued
- Check session TTL hasn't expired (default: 30 minutes)
- Verify session ID is consistent across attempts
- Review session state in logs

## Advanced Configuration

### Custom Handler Priority

The handler runs at priority 95 by default. This can be adjusted if needed:

```yaml
session:
  tool_call_reactor:
    pytest_full_suite_steering_enabled: true
    pytest_full_suite_handler_priority: 95  # Adjust if needed
```

### Session TTL Adjustment

Adjust the session state TTL if needed:

```yaml
session:
  pytest_full_suite_steering_enabled: true
  session_state_ttl: 3600  # 1 hour instead of default 30 minutes
```

## Related Features

- [Pytest Context Saving](pytest-context-saving.md) - Automatically add helpful pytest flags
- [Test Execution Reminder](../test-execution-reminder.md) - Remind agents to run tests before completing tasks
- [Dangerous Command Protection](dangerous-command-protection.md) - Block destructive commands
- [Tool Access Control](tool-access-control.md) - Fine-grained control over tool usage

## Implementation References

- **Handler**: `src/core/services/tool_call_handlers/pytest_full_suite_handler.py`
- **Tests**: `tests/unit/core/services/tool_call_handlers/test_pytest_full_suite_handler.py`
- **Configuration**: `src/core/config/app_config.py`
- **CLI**: `src/core/cli.py`
- **DI Registration**: `src/core/di/services.py`
