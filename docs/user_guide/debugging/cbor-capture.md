# CBOR Wire Capture

CBOR (Concise Binary Object Representation) wire capture provides a high-performance, compact alternative to JSON-based wire capture. It records full HTTP requests and responses in a binary format that is faster to write and takes up less space.

## Overview

CBOR wire capture is designed for high-throughput environments where minimizing I/O overhead is critical. It captures the same detailed information as the JSON format but uses the efficient CBOR binary standard.

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
