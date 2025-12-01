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

For detailed debugging and issue detection, use the dedicated inspection script with powerful analysis capabilities.

### Quick Debugging Workflow

When investigating issues, start with these commands:

```bash
# 1. Auto-detect all issues (START HERE!)
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --detect-issues

# 2. View timeline with timing gaps highlighted
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --timeline --backend gemini-oauth-plan

# 3. Track specific request flow with timing
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --track-request 2 --backend gemini-oauth-plan

# 4. Investigate context around problematic entry
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --around 83 --context 5

# 5. View last entries to see where session stalled
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --last 20 --verbose

# 6. Analyze streaming performance
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --analyze-streaming --backend gemini-oauth-plan
```

### Basic Usage

```bash
# Basic inspection with summary
python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor

# List all backends in the capture file
python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --list-backends

# Show first 20 entries with data preview
python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --entries 20

# Show LAST 20 entries (useful for finding where it stalled)
python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --last 20

# Show specific entry range
python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --range 80-98

# Jump to specific entry
python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor --entry 83 --verbose
```

### Advanced Features

#### Automatic Issue Detection

The `--detect-issues` flag automatically detects and reports:

- **Slow responses**: Timing gaps >10s between entries
- **Rate limiting errors**: Quota exceeded, throttling
- **Missing responses**: Requests with no backend response (stalled sessions)
- **Backend errors**: Error responses from API
- **Empty responses**: completion_tokens=0
- **Model name leaks**: Internal names exposed to client

Example output:

```
=== ISSUES DETECTED ===

SLOW RESPONSE (3 occurrences):
  [!!!] Entry [69]: Long gap: 134.0s between entries [68] and [69]
  [ ! ] Entry [60]: Long gap: 28.8s between entries [59] and [60]

RATE LIMIT (2 occurrences):
  [ ! ] Entry [69]: Rate limiting: quota exhausted, reset after 28s
  [ ! ] Entry [90]: Rate limiting: quota exhausted, reset after 1s

MISSING RESPONSE (1 occurrences):
  [!!!] Entry [94]: Request at [94] has no backend response
```

#### Timeline Visualization

The `--timeline` flag provides a visual timeline with:

- Timing gaps highlighted (>10s marked as "SLOW")
- Millisecond/second deltas between entries
- Entry sequence, direction, size, backend, and session ID
- Perfect for spotting performance issues at a glance

Example:

```bash
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --timeline --backend gemini-oauth-plan
```

Output:

```
=== TIMELINE VIEW ===
[67]  P->B  18:40:04.889  (+25.6s)  108KB  be=gemini-oauth-plan  sid=ebd2f136
[68]  B->P  18:40:04.945  (+56ms)   0B     be=gemini-oauth-plan  sid=ebd2f136
[69]  B->P  18:42:18.937  !!! +134.0s SLOW !!!  402B  be=gemini-oauth-plan
[70]  P->C  18:42:18.982  (+45ms)   0B     be=gemini-oauth-plan  sid=ebd2f136
```

#### Request Flow Tracking

The `--track-request N` flag tracks a specific request through the entire system:

```bash
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --track-request 3 --backend gemini-oauth-plan
```

Shows:
- Complete timeline from client to backend to client
- Timing for each step
- Identifies tool calls, content chunks, errors
- Highlights slow steps (>10s)

Example output:

```
=== REQUEST FLOW TRACKING - Request #3 ===

Request initiated at entry [81]
Model: gemini-oauth-plan:gemini-2.5-pro
Request size: 112,922 bytes

Flow timeline:
  [START] [81] P->B  Request forwarded (t=0.000s)
  [B->P] [82] Stream started (t=0.050s)
  [B->P] [83] Tool call response (t=2.517s)
  [P->C] [84] Forwarded to client (t=2.578s)
```

#### Streaming Performance Analysis

The `--analyze-streaming` flag calculates streaming metrics:

```bash
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --analyze-streaming --backend gemini-oauth-plan
```

Provides:
- Time to First Token (TTFT)
- Total duration and chunk count
- Average time between chunks
- Identifies slow chunks (>5s gaps)

Example output:

```
=== STREAMING PERFORMANCE ANALYSIS ===

--- Stream #2 (Entry [67]) ---
  Time to First Token: 0.055s
  Total Duration: 134.103s
  Chunks: 2
  Total Data: 402 bytes
  Avg Time Between Chunks: 134.103s
  Slow Chunks Detected:
    Entry [69]: 134.0s gap
```

#### Context Window

The `--around N --context M` shows entries around a specific entry:

```bash
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --around 83 --context 5
```

Shows:
- M entries before and after entry N
- Perfect for investigating specific events
- Complete context for debugging

#### Session Grouping

The `--group-by-session` flag groups entries by session ID:

```bash
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --group-by-session
```

Shows all unique sessions with:
- Entry count and duration
- Entry range per session
- Backend for each session

### Filter by Backend

For multi-backend scenarios, use the `--backend` flag:

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

### Combining Features

Multiple features can be combined for powerful analysis:

```bash
# Timeline + issue detection for specific backend
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --detect-issues --timeline --backend gemini-oauth-plan

# Search with context window
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --search "git commit" --around 83 --context 5

# Last entries with verbose metadata
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --last 10 --verbose
```

### Export to JSON

```bash
# Export to JSON for further processing
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --json > analysis.json

# Export only entries from a specific backend
python scripts/inspect_cbor_capture.py \
  var/wire_captures_cbor/session.cbor \
  --backend gemini \
  --json > gemini_only.json
```

