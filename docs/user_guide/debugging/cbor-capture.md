# CBOR Wire Capture

CBOR (Concise Binary Object Representation) wire capture is an advanced byte-precise capture system designed for regression testing and session replay. It captures raw bytes with nanosecond-precision timestamps, enabling exact reproduction of client/server interactions.

## Overview

CBOR capture provides a more precise alternative to JSON wire capture, specifically designed for:

- **Regression Testing**: Replay captured sessions to detect behavioral changes
- **Session Replay**: Reproduce exact client/server interactions
- **Streaming Analysis**: Capture individual SSE chunks with precise timing
- **Debugging**: Inspect exact byte sequences for complex issues

## Key Features

- **Byte-Level Precision**: Captures raw bytes without JSON serialization overhead
- **Nanosecond Timestamps**: CBOR Tag 1 timestamps enable precise timing replay
- **Streaming Support**: Each SSE chunk captured individually with timing metadata
- **Compact Format**: Binary format is more space-efficient than JSON
- **Simulation Engine**: Built-in CLI for inspection and replay
- **Test Integration**: Pytest fixtures for automated testing

## Why CBOR Capture?

### Advantages Over JSON Wire Capture

| Feature | JSON Wire Capture | CBOR Wire Capture |
|---------|------------------|-------------------|
| Format | JSON Lines (.log) | CBOR Binary (.cbor) |
| Precision | Millisecond timestamps | Nanosecond timestamps |
| Streaming | Aggregated chunks | Individual chunks with timing |
| Use Case | Debugging, analysis | Regression testing, replay |
| Overhead | Higher (JSON encoding) | Lower (binary) |
| Tooling | jq, text editors | Simulation CLI |

### When to Use CBOR Capture

- **Regression Testing**: Verify proxy behavior hasn't changed between versions
- **Streaming Debugging**: Analyze exact timing and content of streaming chunks
- **Performance Testing**: Measure precise latency and throughput
- **CI/CD Pipelines**: Automated testing with captured golden sessions
- **Bug Reproduction**: Capture exact conditions that trigger bugs

### When to Use JSON Wire Capture

- **Quick Debugging**: Human-readable format for immediate inspection
- **Log Analysis**: Easy processing with standard tools like jq
- **Ad-hoc Investigation**: No special tools required
- **Development**: Rapid iteration and debugging

## Quick Start

### Enable CBOR Capture

**Via CLI:**

```bash
# Basic CBOR capture
python -m src.core.cli --cbor-capture-dir ./captures

# With specific session ID
python -m src.core.cli \
  --cbor-capture-dir ./captures \
  --cbor-capture-session my-test-session
```

**Via Configuration:**

```yaml
logging:
  cbor_capture_dir: "./captures"
  cbor_capture_session: "session-001"  # Optional: fixed session ID
  capture_flush_interval: 1.0          # Flush interval in seconds
```

**Via Environment Variables:**

```bash
export CBOR_CAPTURE_DIR="./captures"
export CBOR_CAPTURE_SESSION="my-session-id"
```

## Capture File Format

### File Structure

Each session creates a file named `{session_id}.cbor` containing:

1. **File Header**:
   - Magic number (identifies file as CBOR capture)
   - Version number
   - Session metadata
   - Start timestamp

2. **Capture Entries** (sequence of):
   - `ts`: Unix timestamp with nanosecond precision (CBOR Tag 1)
   - `dir`: Direction (0=client→proxy, 1=proxy→client, 2=proxy→backend, 3=backend→proxy)
   - `seq`: Sequence number within session
   - `data`: Raw bytes captured
   - `meta`: Optional metadata (session_id, backend, model, chunk info)

### Direction Codes

- **0**: `client_to_proxy` - Client → Proxy
- **1**: `proxy_to_client` - Proxy → Client
- **2**: `proxy_to_backend` - Proxy → Backend
- **3**: `backend_to_proxy` - Backend → Proxy

## Simulation CLI

The proxy includes a comprehensive CLI for working with CBOR captures.

### Inspect Capture Files

**Basic Inspection:**

```bash
# View summary of a capture file
python -m src.core.simulation.cli inspect ./captures/session-001.cbor
```

Example output:

```
--- Capture File Inspection: ./captures/session-001.cbor ---
Session ID: session-001
Start Timestamp: 1732752000.123456
Statistics:
  Total Entries: 47
  Total Bytes: 125432
  Duration: 3.45s
  Streams: 2

Direction Counts:
  client_to_proxy: 5
  proxy_to_backend: 5
  backend_to_proxy: 32
  proxy_to_client: 5

Timing:
  Min Delta: 0.0001s
  Max Delta: 0.8234s
  Avg Delta: 0.0734s
```

**JSON Output:**

```bash
# Output in JSON format for processing
python -m src.core.simulation.cli inspect ./captures/session-001.cbor --json
```

### List Capture Files

```bash
# List all captures in a directory
python -m src.core.simulation.cli list ./captures/
```

### Replay Captured Sessions

```bash
# Replay against a running proxy instance
python -m src.core.simulation.cli replay ./captures/session-001.cbor \
  --proxy-url http://localhost:8000 \
  --backend-port 8001
```

The replay command:

1. Starts a mock backend server that replays captured backend responses
2. Sends captured client requests to the proxy
3. Validates proxy responses against captured expectations
4. Reports mismatches in content or timing

## Advanced Inspection Script

For detailed debugging and issue detection, use the dedicated inspection script:

### Basic Usage

```bash
# Basic inspection with summary
python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor

# List all backends in the capture file
python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --list-backends

# Show first 20 entries with data preview
python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --entries 20
```

### Filter by Backend

For multi-backend scenarios, use the `--backend` flag to focus on a specific backend:

```bash
# Filter entries by backend
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --backend openai \
  --entries 10

# Analyze only pairs from a specific backend
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --analyze \
  --backend anthropic
```

### Analyze Request/Response Pairs

```bash
# Analyze pairs and detect issues (MOST USEFUL FOR DEBUGGING)
python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --analyze
```

The `--analyze` flag provides:

- **Request/Response Pairing**: Groups entries by request for easier understanding
- **Issue Detection**: Automatically flags problems like:
  - Empty responses (completion_tokens=0)
  - Internal model name leaks
  - Fallback mechanism activation
  - Content loss between backend and client
- **Content Analysis**: Shows character counts, tool call counts, and finish reasons

Example analysis output:

```
--- REQUEST #1 ---
Model: gemini-oauth-antigravity:gemini-2.5-pro
Backend models: {'gemini-2.5-pro', 'code-assist-model'}
Backend content: 0 chars
Client received: (no data, only [DONE]) [14]
ISSUES:
  [!] Internal model name leak: code-assist-model
  [!] Usage-only chunk (completion_tokens=0)
  [!] Immediate stop without content
```

### Filter by Direction

```bash
# Filter by traffic direction
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --direction backend_to_proxy \
  --entries 10

# Combine backend and direction filters
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --backend openai \
  --direction backend_to_proxy \
  --entries 20
```

Available directions:

- `client_to_proxy`
- `proxy_to_client`
- `proxy_to_backend`
- `backend_to_proxy`

### Export to JSON

```bash
# Export to JSON for further processing
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --json > analysis.json

# Export only entries from a specific backend to JSON
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --backend gemini \
  --json > gemini_only.json
```

## Usage Examples

### Capture a Test Session

```bash
# Start proxy with CBOR capture
python -m src.core.cli \
  --cbor-capture-dir ./test-captures \
  --cbor-capture-session regression-test-001 \
  --default-backend openai

# Run your test scenario
# ...

# Inspect the capture
python -m src.core.simulation.cli inspect \
  ./test-captures/regression-test-001.cbor
```

### Regression Testing

```bash
# 1. Capture a known-good session
python -m src.core.cli \
  --cbor-capture-dir ./golden-sessions \
  --cbor-capture-session baseline-v1.0

# 2. After code changes, replay the session
python -m src.core.simulation.cli replay \
  ./golden-sessions/baseline-v1.0.cbor \
  --proxy-url http://localhost:8000

# 3. Check for differences
# The replay command will report any mismatches
```

### Debug Streaming Issues

```bash
# Capture a streaming session
python -m src.core.cli \
  --cbor-capture-dir ./streaming-debug \
  --cbor-capture-session stream-issue-001

# Analyze streaming chunks
python scripts/inspect_cbor_capture.py \
  ./streaming-debug/stream-issue-001.cbor \
  --analyze \
  --direction backend_to_proxy
```

### Performance Analysis

```bash
# Capture session with timing data
python -m src.core.cli \
  --cbor-capture-dir ./performance \
  --cbor-capture-session perf-test-001

# Inspect timing statistics
python -m src.core.simulation.cli inspect \
  ./performance/perf-test-001.cbor
```

## Automated Testing

### Pytest Fixtures

The simulation module provides pytest fixtures for integration testing:

```python
import pytest
from tests.simulation.conftest import (
    create_capture_file,
    create_simple_request_response,
    create_streaming_response,
)

def test_with_captured_session(temp_capture_dir, capture_reader):
    """Test using a captured session."""
    # Create a test capture file
    path = temp_capture_dir / "test.cbor"
    entries = create_simple_request_response(
        request_data=b'{"model": "test", "messages": []}',
        response_data=b'{"choices": [{"message": {"content": "Hello"}}]}',
    )
    create_capture_file(path, entries)
    
    # Load and validate
    session = capture_reader.load(path)
    assert len(session.entries) == 4
    assert session.header.session_id == "test-session"
```

### Streaming Regression Tests

```python
from src.core.domain.cbor_capture import CaptureDirection
from src.core.simulation import CaptureReader

def test_streaming_behavior_matches_capture(capture_file_path):
    """Verify streaming behavior matches a known-good capture."""
    reader = CaptureReader()
    session = reader.load(capture_file_path)
    
    # Get backend streaming chunks
    backend_entries = session.get_backend_entries()
    stream_chunks = [
        e for e in backend_entries
        if e.direction == CaptureDirection.BACKEND_TO_PROXY
        and e.metadata.chunk_index is not None
    ]
    
    # Validate timing deltas are within expected range
    timing_deltas = session.get_timing_deltas()
    assert all(d >= 0 for d in timing_deltas), "Negative timing delta detected"
```

### End-to-End Tests

```python
import pytest
from src.core.simulation import SimulationRunner

@pytest.mark.asyncio
async def test_full_session_replay():
    """End-to-end test using captured session."""
    runner = SimulationRunner(
        proxy_base_url="http://localhost:8000",
        timing_tolerance_ms=100.0,
        speed_multiplier=10.0,  # 10x speed for faster tests
    )
    
    result = await runner.run("./captures/known-good-session.cbor")
    
    assert result.success, result.summary
    assert result.failed_requests == 0
    assert len(result.content_mismatches) == 0
```

### Client Simulation

```python
@pytest.mark.asyncio
async def test_client_simulation(client_simulator_fixture):
    """Test client simulation against a proxy."""
    async with client_simulator_fixture as simulator:
        results = await simulator.replay_session()
        for result in results:
            assert result.success, result.summary
```

## Best Practices

### Organizing Captures

1. **Use Meaningful Session IDs**: Include date and test scenario
   ```bash
   --cbor-capture-session 2025-01-15-login-flow
   ```

2. **Organize by Feature**: Create subdirectories for different features
   ```
   captures/
     auth/
       login-success.cbor
       login-failure.cbor
     streaming/
       long-response.cbor
       chunked-response.cbor
   ```

3. **Version Control**: Store golden sessions in version control
   ```bash
   git add test-captures/golden/*.cbor
   ```

### Capture Golden Sessions

Create captures of known-good behavior for regression testing:

```bash
# Capture baseline behavior
python -m src.core.cli \
  --cbor-capture-dir ./golden-sessions \
  --cbor-capture-session baseline-feature-x

# Tag in version control
git tag golden-feature-x-v1.0
```

### CI/CD Integration

```yaml
# .github/workflows/regression.yml
- name: Run Regression Tests
  run: |
    # Start proxy
    python -m src.core.cli &
    PROXY_PID=$!
    
    # Replay golden sessions
    for capture in golden-sessions/*.cbor; do
      python -m src.core.simulation.cli replay "$capture" \
        --proxy-url http://localhost:8000 || exit 1
    done
    
    # Cleanup
    kill $PROXY_PID
```

### Timing Tolerance

Set appropriate timing tolerance for your test environment:

```python
# Local development: strict timing
runner = SimulationRunner(timing_tolerance_ms=50.0)

# CI environment: relaxed timing
runner = SimulationRunner(timing_tolerance_ms=500.0)
```

### Cleanup

Regularly clean up old capture files:

```bash
# Delete captures older than 30 days
find ./captures -name "*.cbor" -mtime +30 -delete

# Keep only the 10 most recent captures
ls -t ./captures/*.cbor | tail -n +11 | xargs rm
```

## Troubleshooting

### Capture File Not Created

**Problem**: CBOR capture file is not being created

**Solutions**:

- Verify the directory exists: `mkdir -p ./captures`
- Check write permissions: `ls -ld ./captures`
- Ensure path is absolute or relative to working directory
- Check logs for initialization errors

### Replay Failures

**Problem**: Session replay fails with mismatches

**Solutions**:

- Increase timing tolerance: `--timing-tolerance-ms 200`
- Check proxy version matches capture version
- Verify backend is accessible
- Review mismatch details in replay output

### Large Capture Files

**Problem**: Capture files grow too large

**Solutions**:

- Capture only specific test scenarios
- Use shorter test sessions
- Compress old captures: `gzip captures/*.cbor`
- Delete unnecessary captures regularly

### Inspection Errors

**Problem**: Cannot inspect capture file

**Solutions**:

- Verify file is valid CBOR: `file captures/session.cbor`
- Check file is not corrupted
- Ensure capture completed successfully (not interrupted)
- Try with `--json` flag for more details

## Related Features

- [Wire Capture](wire-capture.md) - JSON-based wire capture for debugging
- [Troubleshooting](troubleshooting.md) - General troubleshooting guide
- [Testing Guide](../../development_guide/testing.md) - Development testing practices
