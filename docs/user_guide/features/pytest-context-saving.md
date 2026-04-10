# Pytest Context Saving

Automatically add context-saving flags to pytest commands to preserve context window space while maintaining essential information.

## Overview

The Pytest Context Saving feature automatically adds context-saving flags (`-r fE` and `-q`) to pytest commands to preserve context window space while maintaining essential information. The proxy recognizes pytest commands and intelligently adds flags only when they're not already present, and skips `-q` when verbose output is explicitly requested, reducing output while still showing failed tests and errors.

## Key Features

- **Automatic Detection**: Recognizes pytest commands (`pytest`, `python -m pytest`, etc.)
- **Smart Flag Addition**: Automatically adds `-r fE` (show failed tests and errors) and `-q` (quiet mode) flags, skipping `-q` when verbose output is requested
- **Conditional Logic**: Only adds flags when they're not already present in the command
- **Context Preservation**: Reduces verbose output to save valuable context window tokens
- **Opt-in Feature**: Disabled by default, must be explicitly enabled

## Configuration

Pytest context saving is disabled by default and must be explicitly enabled.

### CLI Flag

```bash
--enable-pytest-context-saving   # Enable pytest context saving
```

### YAML Configuration

```yaml
session:
  tool_call_reactor:
    pytest_context_saving_enabled: true  # Default: false
```

## Usage Examples

### Enable via CLI

```bash
python -m src.core.cli --enable-pytest-context-saving
```

### Enable via YAML

```yaml
# config.yaml
session:
  tool_call_reactor:
    pytest_context_saving_enabled: true
```

Then start the proxy:

```bash
python -m src.core.cli --config config.yaml
```

## Command Transformations

### Basic Command

```bash
# Before context saving:
pytest tests/

# After context saving (automatically modified):
pytest tests/ -r fE -q
```

### Command with Existing Flags

```bash
# If verbose output is requested, skip -q:
pytest tests/ --verbose

# Result: -r fE added, -q skipped
pytest -r fE tests/ --verbose
```

### Complex Command

```bash
# Before:
python -m pytest tests/unit tests/integration

# After:
python -m pytest tests/unit tests/integration -r fE -q
```

## Flag Meanings

### `-r fE`

Shows only failed tests and errors in the summary:

- `f`: Show failed tests
- `E`: Show errors

This eliminates passed tests from the summary, saving tokens.

### `-q`

Quiet mode reduces verbosity:

- Suppresses detailed test collection information
- Reduces progress output
- Shows only essential information

## Benefits

### Context Window Conservation

Reduces verbose pytest output to save tokens:

```bash
# Without context saving:
pytest tests/  # Shows all test details, collection info, passed tests

# With context saving:
pytest tests/ -r fE -q  # Shows only failures and errors, minimal output
```

### Error Visibility

Still shows failed tests and error details with `-r fE`:

```bash
# Failed tests are still visible:
FAILED tests/test_example.py::test_function - AssertionError: ...
ERROR tests/test_example.py::test_setup - RuntimeError: ...
```

### Cleaner Output

Quiet mode with `-q` reduces unnecessary verbosity:

```bash
# Without -q: Shows collection details, progress bars, etc.
# With -q: Shows only test results and failures
```

### Automatic Operation

No need to manually add flags to every pytest command:

```bash
# Agent runs: pytest tests/
# Proxy automatically modifies to: pytest tests/ -r fE -q
```

### Safe Implementation

Only adds flags when they don't already exist:

```bash
# If command already has -r or -q, no modification
pytest tests/ -r fE -q --verbose  # No change
```

## Use Cases

### Long Test Suites

For projects with many tests, context saving dramatically reduces output:

```bash
# 100 tests without context saving: 10,000 tokens
# 100 tests with context saving: 1,000 tokens (only failures shown)
```

### Iterative Development

During iterative development, agents run tests frequently. Context saving reduces cumulative token usage:

```bash
# Agent runs tests 20 times during development
# Without context saving: 200,000 tokens total
# With context saving: 20,000 tokens total
```

### CI/CD Integration

In CI/CD environments, context saving reduces log sizes and focuses on failures:

```bash
# CI runs full test suite
# Context-saved output focuses on failures
# Easier to identify and debug issues
```

### Working with Token-Limited Models

For models with smaller context windows, context saving helps fit more information:

```bash
# Model with 8K context window
# Without context saving: Test output fills 6K tokens
# With context saving: Test output uses 600 tokens
```

## Troubleshooting

**Context saving not working:**

- Verify the feature is enabled (`--enable-pytest-context-saving` or config)
- Check that pytest commands are being recognized
- Review logs for command modification messages
- Ensure the command format matches expected pytest patterns

**Flags not being added:**

- Check if flags are already present in the command
- Verify the command is recognized as a pytest command
- Review logs for parsing errors
- Ensure Tool Call Reactor is enabled

**Too much output still visible:**

- Context saving only adds `-r fE` and `-q` flags (skipping `-q` when verbose output is requested)
- If tests have many failures, all failures will still be shown
- Review if additional pytest flags are needed

**Missing important information:**

- Context saving preserves all failure information
- If specific output is missing, check if it's in the error details
- Review pytest documentation for additional flags
- Consider if `-q` is too aggressive for your use case

**Performance impact:**

- Context saving adds minimal overhead (<1ms per command)
- The benefit (reduced tokens) far outweighs the cost
- Disable if not needed to eliminate any overhead

## Related Features

- [Dynamic Tool Output Compression](dynamic-tool-output-compression.md) - Strategy-based runtime compression of tool outputs during request preparation (complements command rewriting with content-aware reduction)
- [Context Window Enforcement](context-window-enforcement.md) - Enforce per-model context window limits
- [Session Management](session-management.md) - Intelligent session continuity
- [Tool Access Control](tool-access-control.md) - Control which tools can be executed
