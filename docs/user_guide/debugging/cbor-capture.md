# CBOR Wire Capture

CBOR V2 capture records the bytes observed at the proxy boundary in a compact binary format. It captures protocol-boundary traffic, not canonical object serialization.

## Overview

CBOR wire capture is designed for high-throughput environments where minimizing I/O overhead is critical.

The capture contract is boundary-level:

- HTTP request and response bodies are captured as transmitted across the proxy boundary.
- WebSocket payloads are captured as transmitted across the proxy boundary.
- JSON and structured capture semantics are unchanged; CBOR V2 is an additional storage format, not a semantic rewrite.

This means the capture preserves what crossed the proxy boundary, but it does not provide TCP segment, TLS record, or HTTP/2 frame fidelity. It also does not attempt to reconstruct a canonical application object model from the payload.

## Enabling CBOR Capture

You can enable CBOR capture via the CLI or configuration file.

### Via CLI

```bash
python -m src.core.cli --cbor-capture-file var/wire_captures_cbor/session.cbor
```

### Via Configuration

```yaml
logging:
  cbor_capture_file: "var/wire_captures_cbor/session.cbor"
```

## Inspecting CBOR Captures

Since CBOR is a binary format, you cannot read it directly with a text editor. The project provides a dedicated inspection tool: `scripts/inspect_cbor_capture.py`.

### Basic Usage

```bash
python scripts/inspect_cbor_capture.py var/wire_captures_cbor/session.cbor
```

This prints a summary of the capture file, including session ID, creation time, total entry count, direction breakdown, total bytes, and duration.

To suppress entry output and show only the summary, run the tool without `--entries` or pass `--entries 0`.

### Filtering Entries

#### By Time Range

Filter entries based on timestamps. You can use Unix timestamps, ISO datetime strings, or time-only strings (assumes today's date).

```bash
# Filter by Unix timestamp
python scripts/inspect_cbor_capture.py session.cbor --start-time 1702300000 --end-time 1702400000

# Filter by ISO datetime
python scripts/inspect_cbor_capture.py session.cbor --start-time "2024-01-15T10:00:00"

# Filter by time of day
python scripts/inspect_cbor_capture.py session.cbor --start-time "10:30:00" --end-time "11:00:00"
```

#### By Backend

```bash
# Show only entries for the OpenAI backend
python scripts/inspect_cbor_capture.py session.cbor --backend openai

# List all unique backends present in a capture
python scripts/inspect_cbor_capture.py session.cbor --list-backends
```

#### By Direction

```bash
# Show only backend responses
python scripts/inspect_cbor_capture.py session.cbor --direction backend_to_proxy
```

Available directions: `client_to_proxy`, `proxy_to_client`, `proxy_to_backend`, `backend_to_proxy`.

#### By Session

Filter by a specific session ID or by a substring match against session identifiers.

```bash
# Filter by exact session ID
python scripts/inspect_cbor_capture.py session.cbor --session-id llm-b2bua-abc123

# Filter by substring against asid/sid or bsid (case-insensitive)
python scripts/inspect_cbor_capture.py session.cbor --session-substring b2bu
```

### Entry Navigation

Control which entries are shown and how they appear.

#### Number of Entries

```bash
# Show first 10 entries
python scripts/inspect_cbor_capture.py session.cbor --entries 10

# Show last 20 entries
python scripts/inspect_cbor_capture.py session.cbor --last 20

# Show entries in a specific range
python scripts/inspect_cbor_capture.py session.cbor --range 80-98

# Show 5 entries before and after entry 83
python scripts/inspect_cbor_capture.py session.cbor --around 83 --context 5

# Jump directly to entry 83
python scripts/inspect_cbor_capture.py session.cbor --entry 83
```

#### Verbose Metadata

The `--verbose` flag prints full metadata for each entry. For V2 captures, compact metadata keys (like `ss`, `se`, `ttfb`, `sc`) are automatically expanded into readable names (like `is_stream_start`, `is_stream_end`, `ttfb_ms`, `status_code`).

```bash
python scripts/inspect_cbor_capture.py session.cbor --entries 5 --verbose
```

#### Search and Hex

```bash
# Find entries containing a specific term (searches data and metadata)
python scripts/inspect_cbor_capture.py session.cbor --search "error" --verbose

# Show full hex dump of entry data instead of text preview
python scripts/inspect_cbor_capture.py session.cbor --entries 3 --hex
```

#### Data Preview Size

```bash
# Show up to 500 bytes of data per entry instead of the default 200
python scripts/inspect_cbor_capture.py session.cbor --entries 10 --max-data 500
```

### Analysis Modes

The tool includes several analysis modes to diagnose problems and understand traffic patterns.

#### Request/Response Analysis

Groups client requests with their correlated backend traffic and shows model, timing, content summary, tool calls, and detected issues. Correlation uses V2 `request_id` metadata when available, with session-based fallback for older captures.

```bash
# Analyze all request/response pairs
python scripts/inspect_cbor_capture.py session.cbor --analyze

# Analyze only traffic from a specific backend
python scripts/inspect_cbor_capture.py session.cbor --analyze --backend openai
```

Sample output per request:

```
--- REQUEST #2 ---
Model: zai-coding-plan:glm-4.7
Timing: TTFT=1.149s, Duration=2.656s
Backend models: {'claude-haiku-4.5'}
Backend content: 34 chars, 1 tool_calls (bash)
Client received: (no data, only [DONE])
ISSUES:
  [!] Backend Error: Insufficient balance or no resource package. Please recharge.
```

#### Streaming Performance Analysis

Reports time-to-first-token, total duration, chunk count, and per-chunk timing for each backend stream. Respects V2 stream markers (`stream_start`, `stream_end`) and correlates chunks by request id so interleaved requests are not conflated.

```bash
python scripts/inspect_cbor_capture.py session.cbor --analyze-streaming

# Filter to one backend's streams
python scripts/inspect_cbor_capture.py session.cbor --analyze-streaming --backend kiro-oauth-auto
```

#### Detect Issues

Automatically scans for common problems: slow response gaps (>10s between entries in the same session), rate limiting (429), backend errors, and missing responses (client requests never forwarded or without backend replies).

```bash
python scripts/inspect_cbor_capture.py session.cbor --detect-issues

# Combine with analysis
python scripts/inspect_cbor_capture.py session.cbor --analyze --detect-issues
```

#### Timeline View

Displays entries chronologically with inter-entry timing gaps. Gaps larger than 1 second are annotated; gaps larger than 10 seconds are marked as `!!! SLOW !!!`.

```bash
python scripts/inspect_cbor_capture.py session.cbor --timeline

# Timeline for a single backend
python scripts/inspect_cbor_capture.py session.cbor --timeline --backend gemini-oauth-plan
```

#### HTTP Status Summary

Aggregates HTTP status codes from V2 capture metadata, showing both overall distribution and per-backend breakdowns (including 429 rate-limit ratios).

```bash
python scripts/inspect_cbor_capture.py session.cbor --status-summary
```

#### Request Flow Tracking

Walk a single request through the entire proxy lifecycle, showing each hop with its elapsed time and a human-readable description of what each entry does.

```bash
# Track the 3rd request
python scripts/inspect_cbor_capture.py session.cbor --track-request 3

# Track a specific backend's request
python scripts/inspect_cbor_capture.py session.cbor --track-request 2 --backend openai
```

#### Group by Session

Summarize entries grouped by their session identifier, showing entry counts and time ranges per session.

```bash
python scripts/inspect_cbor_capture.py session.cbor --group-by-session
```

### Exporting to JSON

Export the capture to structured JSON for processing with external tools. Each entry includes its direction, timestamp, base64-encoded data, parsed SSE/JSON events, and normalized V2 metadata.

```bash
# Export to stdout
python scripts/inspect_cbor_capture.py session.cbor --json > export.json

# Export directly to a file
python scripts/inspect_cbor_capture.py session.cbor --json output.json

# Export only one backend's entries
python scripts/inspect_cbor_capture.py session.cbor --backend openai --json > openai_only.json
```

### V2 Capture Format Notes

CBOR V2 captures include several enhancements over earlier versions:

- **Compact metadata keys**: Keys like `ss` (stream start), `se` (stream end), `ttfb` (time-to-first-byte), `sc` (status code), and `rid` (request id) are stored compactly. The inspector expands these into full names in verbose and JSON output.
- **Compressed payloads**: Large backend payloads may be zlib-compressed with `"enc": "zlib"`. The inspector transparently decompresses these on load.
- **Stream markers**: Backend responses include empty marker entries with `ss` or `se` flags. The inspector skips these when counting payload chunks and uses explicit timing metadata (`ttfb_ms`, `latency_ms`, `stream_duration_ms`) for accurate metrics.
- **End-of-stream metadata**: Stream-end markers carry `eos`, `eos_reason`, `eos_termination_category`, and `eos_error_classification` fields that describe why a stream terminated.

The inspector only supports capture version 2. Older formats are rejected with an error.

### Combining Features

All analysis and filtering flags can be combined in a single invocation.

```bash
# Backend-focused investigation
python scripts/inspect_cbor_capture.py session.cbor --backend kiro-oauth-auto --analyze --detect-issues --timeline

# Time-bounded debugging with verbose output
python scripts/inspect_cbor_capture.py session.cbor --start-time "2024-01-15T10:00:00" --end-time "2024-01-15T11:00:00" --detect-issues --entries 50 --verbose

# Full diagnostic sweep for one session
python scripts/inspect_cbor_capture.py session.cbor --session-id llm-b2bu --analyze --analyze-streaming --detect-issues --status-summary
```

## Security and Scope Notes

- Secrets are stored as transmitted on the wire. If a request or response includes credentials, tokens, or other sensitive values, the capture records those bytes unless an upstream redaction step has already changed them.
- Scoped OAuth traffic is captured when it crosses the proxy boundary, including proxied client-to-provider and provider-to-client exchanges.
- Background OAuth refresh, probes, and other internal non-proxied OAuth activity are outside the capture contract and are not recorded by CBOR V2.
