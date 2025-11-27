# Debugging Guide

This guide covers debugging techniques and tools for developing and troubleshooting the LLM Interactive Proxy.

## Overview

The proxy provides several debugging tools to help you understand request/response flows, diagnose issues, and verify behavior:

- **Log Files**: Detailed logging with PID-based filenames for concurrent execution
- **Wire Captures**: Record all traffic between client, proxy, and backend
- **CBOR Inspection Tools**: Analyze captured traffic with built-in utilities
- **Simulation Mode**: Replay captured sessions for testing

## Log Files

### Location

All log files are stored in `./var/logs/` with PIDs in filenames for safe concurrent execution:

```
var/logs/
├── proxy_12345.log
├── proxy_12346.log
└── ...
```

### Log Levels

Configure logging verbosity via CLI or environment:

```bash
# CLI
python -m src.core.cli --log-level DEBUG

# Environment
export LOG_LEVEL=DEBUG
```

Available levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

### Structured Logging

The proxy uses structured logging with contextual information:

```python
logger.info(
    "Forwarding request",
    extra={
        "backend": "openai",
        "model": "gpt-4",
        "session_id": "abc123",
    }
)
```

## Wire Captures

Wire captures record all traffic between client, proxy, and backend for analysis and replay.

### Enabling Wire Captures

#### JSON Format

```bash
# Enable JSON wire capture
python -m src.core.cli \
  --default-backend openai \
  --enable-wire-capture-json
```

JSON captures are stored in `./var/wire_captures_json/`

#### CBOR Format (Recommended)

```bash
# Enable CBOR wire capture (more efficient)
python -m src.core.cli \
  --default-backend openai \
  --enable-wire-capture-cbor
```

CBOR captures are stored in `./var/wire_captures_cbor/`

### Capture File Structure

Each capture file contains:

- **Timestamp**: When the traffic occurred
- **Direction**: Traffic flow (client_to_proxy, proxy_to_backend, etc.)
- **Data**: Request or response payload
- **Metadata**: Session ID, model, backend, etc.

## CBOR Inspection Tools

CBOR (Concise Binary Object Representation) is the recommended format for wire captures due to its efficiency and binary safety.

### Method 1: Built-in CLI Tool

The proxy includes a built-in CLI tool for inspecting CBOR captures:

```bash
# Basic inspection (shows summary)
./.venv/Scripts/python.exe -m src.core.simulation.cli inspect \
  --capture ./var/wire_captures_cbor/capture_file.cbor

# Show first 5 entries with details
./.venv/Scripts/python.exe -m src.core.simulation.cli inspect \
  --capture ./var/wire_captures_cbor/capture_file.cbor \
  --entries 5

# Output as JSON for further processing
./.venv/Scripts/python.exe -m src.core.simulation.cli inspect \
  --capture ./var/wire_captures_cbor/capture_file.cbor \
  --json > capture_summary.json
```

### Method 2: Inspection Script (Recommended for Debugging)

The dedicated inspection script provides advanced analysis capabilities:

```bash
# Basic inspection
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/capture_file.cbor

# List all backends in the capture file
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/capture_file.cbor \
  --list-backends

# Show first 10 entries with data preview
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/capture_file.cbor \
  --entries 10

# Filter entries by backend
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/capture_file.cbor \
  --backend openai \
  --entries 10

# Analyze request/response pairs and detect issues (MOST USEFUL)
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/capture_file.cbor \
  --analyze

# Analyze only pairs from a specific backend
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/capture_file.cbor \
  --analyze \
  --backend anthropic

# Filter by traffic direction
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/capture_file.cbor \
  --entries 20 \
  --direction backend_to_proxy

# Combine backend and direction filters
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/capture_file.cbor \
  --backend openai \
  --direction backend_to_proxy \
  --entries 20

# Export to JSON
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/capture_file.cbor \
  --json > analysis.json

# Export only entries from a specific backend to JSON
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/capture_file.cbor \
  --backend gemini \
  --json > gemini_only.json
```

### Automatic Issue Detection

The `--analyze` flag automatically detects common issues:

- **Empty Responses**: Responses with `completion_tokens=0`
- **Model Name Leaks**: Internal model names exposed to client
- **Fallback Activation**: When fallback mechanisms trigger
- **Content Loss**: Missing content between backend and client
- **Token Mismatches**: Usage discrepancies

Example output:

```
=== ISSUES DETECTED ===

Issue #1: Empty Response
  Entry: 42
  Direction: backend_to_proxy
  Details: Response has completion_tokens=0

Issue #2: Model Name Leak
  Entry: 45
  Direction: proxy_to_client
  Details: Internal model 'code-assist-model' leaked instead of 'gpt-4'
```

### Method 3: Programmatic Access

Use the `CaptureReader` class in your code:

```python
from src.core.simulation.capture_reader import CaptureReader

# Load capture file
reader = CaptureReader()
session = reader.load("./var/wire_captures_cbor/capture_file.cbor")

# Get summary
summary = reader.summarize()
print(f"Total entries: {summary['total_entries']}")
print(f"Session ID: {summary['session_id']}")

# Iterate through entries
for entry in session.entries:
    print(f"[{entry.timestamp}] {entry.direction}")
    print(f"Data: {entry.data}")
    
    # Filter by direction
    if entry.direction == "backend_to_proxy":
        # Analyze backend responses
        pass
```

## Simulation Mode

Replay captured sessions for testing without making real API calls.

### Basic Simulation

```bash
# Replay a captured session
./.venv/Scripts/python.exe -m src.core.simulation.cli simulate \
  --capture ./var/wire_captures_cbor/capture_file.cbor
```

### Use Cases

1. **Testing Changes**: Verify behavior changes without API costs
2. **Reproducing Bugs**: Replay problematic sessions
3. **Performance Testing**: Measure processing overhead
4. **Integration Testing**: Test middleware and transformations

## Common Debugging Scenarios

### Scenario 1: Request Not Reaching Backend

**Symptoms**: Client receives error but backend shows no traffic

**Debug Steps**:

1. Enable wire capture:
   ```bash
   python -m src.core.cli --enable-wire-capture-cbor
   ```

2. Inspect capture for `client_to_proxy` entries:
   ```bash
   ./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
     var/wire_captures_cbor/latest.cbor \
     --direction client_to_proxy
   ```

3. Check for middleware errors in logs:
   ```bash
   grep "ERROR" var/logs/proxy_*.log
   ```

### Scenario 2: Response Transformation Issues

**Symptoms**: Backend returns data but client receives different content

**Debug Steps**:

1. Capture traffic with CBOR:
   ```bash
   python -m src.core.cli --enable-wire-capture-cbor
   ```

2. Analyze request/response pairs:
   ```bash
   ./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
     var/wire_captures_cbor/latest.cbor \
     --analyze
   ```

3. Look for content loss or transformation issues in the analysis output

### Scenario 3: Streaming Issues

**Symptoms**: Streaming responses incomplete or malformed

**Debug Steps**:

1. Enable debug logging:
   ```bash
   python -m src.core.cli --log-level DEBUG --enable-wire-capture-cbor
   ```

2. Check streaming chunk processing in logs:
   ```bash
   grep "stream" var/logs/proxy_*.log
   ```

3. Inspect streaming chunks:
   ```bash
   ./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
     var/wire_captures_cbor/latest.cbor \
     --direction backend_to_proxy \
     --entries 50
   ```

### Scenario 4: Authentication Failures

**Symptoms**: 401/403 errors from backend

**Debug Steps**:

1. Check API key configuration:
   ```bash
   # Verify environment variables
   echo $OPENAI_API_KEY
   ```

2. Inspect request headers (keys are redacted in logs):
   ```bash
   grep "Authorization" var/logs/proxy_*.log
   ```

3. Verify backend initialization:
   ```bash
   grep "initialize" var/logs/proxy_*.log
   ```

### Scenario 5: Model Name Issues

**Symptoms**: Wrong model used or model name leaks

**Debug Steps**:

1. Enable wire capture and analyze:
   ```bash
   ./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py \
     var/wire_captures_cbor/latest.cbor \
     --analyze
   ```

2. Check for model name leaks in the analysis output

3. Verify model name rewrite rules:
   ```bash
   grep "model.*rewrite" var/logs/proxy_*.log
   ```

## Debugging Tools Reference

### Environment Variables

```bash
# Logging
export LOG_LEVEL=DEBUG
export LOG_FORMAT=json  # or 'text'

# Wire Captures
export ENABLE_WIRE_CAPTURE_JSON=true
export ENABLE_WIRE_CAPTURE_CBOR=true

# Debugging Features
export DISABLE_HEALTH_CHECKS=true  # Skip backend health checks
```

### CLI Flags

```bash
# Logging
--log-level DEBUG
--log-file custom_log.log

# Wire Captures
--enable-wire-capture-json
--enable-wire-capture-cbor

# Debugging
--disable-health-checks
--enable-request-logging
```

### Useful Log Patterns

```bash
# Find errors
grep "ERROR" var/logs/proxy_*.log

# Find specific session
grep "session_id=abc123" var/logs/proxy_*.log

# Find backend calls
grep "Forwarding to" var/logs/proxy_*.log

# Find authentication issues
grep -i "auth" var/logs/proxy_*.log

# Find model overrides
grep "effective_model" var/logs/proxy_*.log
```

## Performance Debugging

### Measuring Request Latency

The proxy includes performance tracking:

```python
from src.performance_tracker import PerformanceTracker

tracker = PerformanceTracker()

with tracker.track("backend_call"):
    response = await backend.chat_completions(...)

# View metrics
print(tracker.get_metrics())
```

### Profiling

Use Python's built-in profiler:

```bash
# Profile the proxy
python -m cProfile -o profile.stats -m src.core.cli

# Analyze results
python -m pstats profile.stats
```

## Testing with Wire Captures

### Creating Test Fixtures

1. Capture a real session:
   ```bash
   python -m src.core.cli --enable-wire-capture-cbor
   ```

2. Use the capture in tests:
   ```python
   from src.core.simulation.capture_reader import CaptureReader
   
   def test_with_capture():
       reader = CaptureReader()
       session = reader.load("tests/fixtures/test_session.cbor")
       
       # Use captured data in test
       for entry in session.entries:
           if entry.direction == "client_to_proxy":
               # Test request handling
               pass
   ```

### Regression Testing

Use captures to prevent regressions:

```python
@pytest.mark.parametrize("capture_file", [
    "tests/fixtures/openai_session.cbor",
    "tests/fixtures/anthropic_session.cbor",
])
def test_no_regression(capture_file):
    """Ensure captured sessions still work correctly."""
    reader = CaptureReader()
    session = reader.load(capture_file)
    
    # Replay and verify behavior
    ...
```

## Best Practices

1. **Always Enable Wire Capture for Debugging**: Use CBOR format for efficiency
2. **Use Structured Logging**: Include context (session_id, backend, model)
3. **Analyze with --analyze Flag**: Automatically detect common issues
4. **Keep Captures for Regression Tests**: Save problematic sessions as test fixtures
5. **Check Logs First**: Often faster than inspecting wire captures
6. **Use Simulation Mode**: Test changes without API costs
7. **Profile Performance**: Identify bottlenecks with profiling tools
8. **Clean Up Old Captures**: Wire captures can consume disk space

## Related Documentation

- [Architecture](architecture.md) - System architecture overview
- [Testing](testing.md) - Testing guidelines
- [Adding Backends](adding-backends.md) - Backend development guide
- [AGENTS.md](../../dev/AGENTS.md) - Development guidelines
