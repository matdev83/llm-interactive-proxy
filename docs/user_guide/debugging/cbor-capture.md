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

This will print a summary of the capture file, including session ID, duration, and entry counts.

### Filtering Entries

You can filter entries to find specific requests or time ranges.

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
```

#### By Direction

```bash
# Show only backend responses
python scripts/inspect_cbor_capture.py session.cbor --direction backend_to_proxy
```

### Advanced Analysis

The tool includes powerful analysis features to help debug issues.

#### Detect Issues

Automatically scan for common problems like errors, slow responses, or rate limits.

```bash
python scripts/inspect_cbor_capture.py session.cbor --detect-issues
```

#### Request/Response Analysis

Analyze paired requests and responses to see latency, token usage, and content.

```bash
python scripts/inspect_cbor_capture.py session.cbor --analyze
```

#### Timeline View

Visualize traffic over time to identify gaps or latency spikes.

```bash
python scripts/inspect_cbor_capture.py session.cbor --timeline
```

### Exporting to JSON

If you need to process the data with other tools (like `jq`), you can export it to JSON.

```bash
python scripts/inspect_cbor_capture.py session.cbor --json > export.json
```

## Security and Scope Notes

- Secrets are stored as transmitted on the wire. If a request or response includes credentials, tokens, or other sensitive values, the capture records those bytes unless an upstream redaction step has already changed them.
- Scoped OAuth traffic is captured when it crosses the proxy boundary, including proxied client-to-provider and provider-to-client exchanges.
- Background OAuth refresh, probes, and other internal non-proxied OAuth activity are outside the capture contract and are not recorded by CBOR V2.
