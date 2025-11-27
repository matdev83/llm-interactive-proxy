# Pytest Output Compression

Automatically compress verbose pytest output to preserve context window space while maintaining error information.

## Overview

The Pytest Output Compression feature automatically compresses verbose pytest output to preserve context window space while maintaining all essential error information. The proxy recognizes pytest commands, removes verbose timing information and passed test results, but keeps failed tests and error messages intact. This helps agents work more efficiently by reducing token usage without losing critical debugging information.

## Key Features

- **Automatic Detection**: Recognizes pytest commands (`pytest`, `python -m pytest`, `py.test`, etc.)
- **Smart Filtering**: Removes verbose timing info and `PASSED` test results
- **Error Preservation**: Keeps `FAILED` tests and error messages intact
- **Configurable**: Can be enabled/disabled globally or per-session
- **Compression Stats**: Logs compression ratios for monitoring
- **Enabled by Default**: Works out of the box with sensible defaults

## Configuration

Pytest compression is enabled by default and can be controlled via CLI flag, environment variable, or YAML configuration.

### Configuration Precedence

CLI > Environment Variable > YAML Configuration

### CLI Flag

```bash
--enable-pytest-compression   # Explicitly enable compression
```

### Environment Variable

```bash
export PYTEST_COMPRESSION_ENABLED=true  # or false
```

### YAML Configuration

```yaml
session:
  pytest_compression_enabled: true  # Default: true
```

## Usage Examples

### Enable Compression (Default)

Compression is enabled by default, no configuration needed:

```bash
python -m src.core.cli --default-backend openai
```

### Explicitly Enable

```bash
python -m src.core.cli --enable-pytest-compression
```

### Disable Compression

```bash
# Via CLI
python -m src.core.cli --disable-pytest-compression

# Via environment variable
export PYTEST_COMPRESSION_ENABLED=false
python -m src.core.cli

# Via YAML
# config.yaml:
# session:
#   pytest_compression_enabled: false
```

## Output Transformation

### Before Compression (Verbose)

```
test_example.py::test_function PASSED                    [ 50%] 0.001s setup 0.002s call 0.001s teardown
test_example.py::test_another PASSED                     [ 75%] 0.001s setup 0.002s call 0.001s teardown
test_example.py::test_failure FAILED                     [100%] 0.001s setup 0.003s call 0.001s teardown

FAILED test_example.py::test_failure - AssertionError: expected 5 but got 3
```

### After Compression (Concise)

```
test_example.py::test_failure FAILED                     [100%]

FAILED test_example.py::test_failure - AssertionError: expected 5 but got 3
```

### What Gets Removed

- Timing information (`0.001s setup`, `0.002s call`, `0.001s teardown`)
- `PASSED` test results (only failures are kept)
- Verbose progress indicators (when not essential)

### What Gets Preserved

- All `FAILED` test results
- Error messages and stack traces
- Test names and locations
- Progress percentages (e.g., `[100%]`)
- Summary information

## Use Cases

### Context Window Conservation

Save valuable context window tokens by removing verbose pytest output:

```bash
# Agent runs pytest with many tests
pytest tests/

# Without compression: 5000 tokens
# With compression: 500 tokens (only failures shown)
```

### Long Test Suites

For projects with large test suites, compression dramatically reduces output:

```bash
# 100 tests, 95 pass, 5 fail
# Without compression: Shows all 100 results + timing
# With compression: Shows only 5 failures
```

### Iterative Development

During iterative development, agents often run tests multiple times. Compression reduces cumulative token usage:

```bash
# Agent runs tests 10 times during development
# Without compression: 50,000 tokens total
# With compression: 5,000 tokens total
```

### CI/CD Integration

In CI/CD environments where test output is captured, compression reduces log sizes:

```bash
# CI runs full test suite
# Compressed output focuses on failures
# Easier to identify and debug issues
```

## Compression Statistics

The proxy logs compression statistics for monitoring:

```
INFO: Pytest output compressed: 4523 bytes -> 892 bytes (80.3% reduction)
```

This helps you understand:

- How much space is being saved
- Whether compression is working effectively
- If adjustments are needed

## Troubleshooting

**Compression not working:**

- Verify the feature is enabled (check config/env/CLI)
- Ensure pytest commands are being recognized
- Check logs for compression messages
- Verify the output format matches expected pytest format

**Too much output still visible:**

- Compression only removes passed tests and timing
- Failed tests and errors are always preserved
- Consider if the test suite has many failures
- Review compression statistics in logs

**Missing important information:**

- Compression preserves all failure information
- If specific output is missing, it may not be pytest-related
- Check if the output format is non-standard
- Review logs for parsing errors

**Performance impact:**

- Compression adds minimal overhead (<1ms per command)
- The benefit (reduced tokens) far outweighs the cost
- Disable if not needed to eliminate any overhead

## Related Features

- [Pytest Context Saving](pytest-context-saving.md) - Automatically add context-saving flags to pytest commands
- [Context Window Enforcement](context-window-enforcement.md) - Enforce per-model context window limits
- [Session Management](session-management.md) - Intelligent session continuity
