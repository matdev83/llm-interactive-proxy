# Wire Capture

Wire capture records all HTTP traffic between clients and LLM backends for debugging and analysis, capturing exact requests and responses without logging contamination.

## Overview

The proxy's wire capture system provides detailed visibility into all communication flows:

- Client to Proxy (inbound requests)
- Proxy to Backend (outbound requests)
- Backend to Proxy (inbound responses)
- Proxy to Client (outbound responses)

Wire capture is essential for debugging complex issues, analyzing model behavior, and understanding exactly what data flows through the proxy.

## Key Features

- **Multiple Formats**: JSON Lines (current), legacy human-readable, and structured JSON formats
- **High Performance**: Buffered writes with configurable flush intervals
- **Streaming Support**: Captures streaming responses with chunk-level detail
- **Security Aware**: Respects prompt redaction settings to mask API keys
- **Rotation Support**: Automatic file rotation based on size limits
- **Rich Metadata**: Includes session IDs, backend info, model names, and timing data

## Quick Start

### Enable via CLI

```bash
# Basic wire capture
python -m src.core.cli --capture-file logs/wire_capture.log

# With custom buffer size
python -m src.core.cli --capture-file logs/wire_capture.log
```

### Enable via Configuration

```yaml
logging:
  capture_file: "logs/wire_capture.log"
```

### Enable via Environment Variable

```bash
export WIRE_CAPTURE_FILE="logs/wire_capture.log"
```

## Configuration

### Basic Configuration

```yaml
logging:
  capture_file: "logs/wire_capture.log"
```

### Advanced Configuration

```yaml
logging:
  capture_file: "logs/wire_capture.log"
  
  # Performance tuning
  capture_buffer_size: 65536          # 64KB buffer (default)
  capture_flush_interval: 1.0         # Flush every 1 second
  capture_max_entries_per_flush: 100  # Max entries per flush
  
  # File rotation
  capture_max_bytes: 104857600         # 100MB per file
  capture_max_files: 5                # Keep 5 rotated files
  capture_total_max_bytes: 524288000   # 500MB total cap
```

### Configuration Options

- **capture_file**: Path to the wire capture log file
- **capture_buffer_size**: Buffer size in bytes (default: 65536 = 64KB)
- **capture_flush_interval**: How often to flush buffer to disk in seconds (default: 1.0)
- **capture_max_entries_per_flush**: Maximum entries to write per flush (default: 100)
- **capture_max_bytes**: Maximum size per file before rotation (default: 100MB)
- **capture_max_files**: Number of rotated files to keep (default: 5)
- **capture_total_max_bytes**: Total maximum disk usage across all files (default: 500MB)

## Wire Capture Format

### Current Format: Buffered JSON Lines

The current wire capture format uses JSON Lines (one JSON object per line) for high performance and easy processing:

```json
{
  "timestamp_iso": "2025-01-10T15:58:41.039145+00:00",
  "timestamp_unix": 1736524721.039145,
  "direction": "outbound_request",
  "source": "127.0.0.1(Cline/1.0)",
  "destination": "qwen-oauth",
  "session_id": "session-123",
  "backend": "qwen-oauth",
  "model": "qwen3-coder-plus",
  "key_name": "primary",
  "content_type": "json",
  "content_length": 1247,
  "payload": {
    "messages": [{"role": "user", "content": "..."}],
    "model": "qwen3-coder-plus",
    "temperature": 0.7
  },
  "metadata": {
    "client_host": "127.0.0.1",
    "user_agent": "Cline/1.0",
    "request_id": "req_abc123"
  }
}
```

### Direction Values

- **inbound_request**: Client → Proxy (request received from client)
- **outbound_request**: Proxy → Backend (request sent to LLM backend)
- **inbound_response**: Backend → Proxy (response received from backend)
- **stream_start**: Start of a streaming response
- **stream_chunk**: Individual chunk in a streaming response
- **stream_end**: End of a streaming response

### Field Descriptions

- **timestamp_iso**: ISO 8601 formatted timestamp with timezone
- **timestamp_unix**: Unix timestamp (seconds since epoch)
- **direction**: Traffic direction (see Direction Values above)
- **source**: Source of the traffic (IP address and user agent)
- **destination**: Destination backend name
- **session_id**: Unique session identifier
- **backend**: Backend connector name
- **model**: Model name being used
- **key_name**: Environment variable name for the API key (not the actual key)
- **content_type**: Content type of the payload
- **content_length**: Size of the payload in bytes
- **payload**: The actual request or response data
- **metadata**: Additional metadata (client info, request ID, etc.)

## Usage Examples

### Basic Debugging

Capture all traffic for a debugging session:

```bash
python -m src.core.cli \
  --capture-file logs/debug_session.log \
  --default-backend openai
```

### High-Volume Capture

For high-traffic scenarios, increase buffer size and flush interval:

```bash
python -m src.core.cli \
  --capture-file logs/high_volume.log \
  --default-backend anthropic
```

With configuration:

```yaml
logging:
  capture_file: "logs/high_volume.log"
  capture_buffer_size: 131072        # 128KB buffer
  capture_flush_interval: 2.0        # Flush every 2 seconds
  capture_max_entries_per_flush: 200
```

### Rotating Capture Files

Prevent unbounded disk usage with rotation:

```yaml
logging:
  capture_file: "logs/wire_capture.log"
  capture_max_bytes: 52428800        # 50MB per file
  capture_max_files: 10              # Keep 10 files
  capture_total_max_bytes: 524288000 # 500MB total
```

## Processing Wire Capture Files

### Using jq for Analysis

Wire capture files use JSON Lines format, making them easy to process with `jq`:

#### Count Requests by Backend

```bash
jq -r 'select(.direction=="outbound_request") | .backend' logs/wire_capture.log | sort | uniq -c
```

#### Extract All User Messages

```bash
jq -r 'select(.direction=="outbound_request") | .payload.messages[]? | select(.role=="user") | .content' logs/wire_capture.log
```

#### Find Failed Requests

```bash
jq 'select(.direction=="inbound_response" and (.payload.error or .payload.choices == null))' logs/wire_capture.log
```

#### Calculate Token Usage by Model

```bash
jq -r 'select(.direction=="inbound_response" and .payload.usage) | "\(.model) \(.payload.usage.total_tokens // (.payload.usage.prompt_tokens + .payload.usage.completion_tokens))"' logs/wire_capture.log
```

#### Analyze Streaming Responses

```bash
# Count streaming chunks per session
jq -r 'select(.direction=="stream_chunk") | .session_id' logs/wire_capture.log | sort | uniq -c

# Find sessions with streaming errors
jq 'select(.direction=="stream_end" and .metadata.error)' logs/wire_capture.log
```

### Using Python for Analysis

```python
import json

# Read and parse wire capture file
with open('logs/wire_capture.log', 'r') as f:
    entries = [json.loads(line) for line in f]

# Analyze by direction
from collections import Counter
directions = Counter(e['direction'] for e in entries)
print(f"Direction counts: {directions}")

# Find slow requests (>2 seconds)
slow_requests = []
for i, entry in enumerate(entries):
    if entry['direction'] == 'outbound_request':
        # Find corresponding response
        for j in range(i+1, len(entries)):
            if entries[j]['direction'] == 'inbound_response' and entries[j]['session_id'] == entry['session_id']:
                duration = entries[j]['timestamp_unix'] - entry['timestamp_unix']
                if duration > 2.0:
                    slow_requests.append({
                        'session': entry['session_id'],
                        'model': entry['model'],
                        'duration': duration
                    })
                break

print(f"Slow requests: {len(slow_requests)}")
```

## Use Cases

### Debugging Model Behavior

Capture and analyze exactly what prompts are sent to models:

```bash
# Enable capture
python -m src.core.cli --capture-file logs/model_debug.log

# After session, extract prompts
jq -r 'select(.direction=="outbound_request") | .payload.messages' logs/model_debug.log
```

### Analyzing Token Usage

Track token consumption across sessions:

```bash
# Extract token usage
jq -r 'select(.direction=="inbound_response" and .payload.usage) | 
  "\(.timestamp_iso) \(.model) prompt:\(.payload.usage.prompt_tokens) completion:\(.payload.usage.completion_tokens) total:\(.payload.usage.total_tokens)"' \
  logs/wire_capture.log
```

### Investigating Errors

Find and analyze error responses:

```bash
# Find all errors
jq 'select(.direction=="inbound_response" and .payload.error)' logs/wire_capture.log

# Group errors by type
jq -r 'select(.direction=="inbound_response" and .payload.error) | .payload.error.type' logs/wire_capture.log | sort | uniq -c
```

### Performance Analysis

Measure request/response latency:

```bash
# Extract timing data
jq -r 'select(.direction=="inbound_response") | 
  "\(.session_id) \(.timestamp_unix)"' logs/wire_capture.log
```

### Streaming Analysis

Analyze streaming response patterns:

```bash
# Count chunks per streaming session
jq -r 'select(.direction=="stream_chunk") | .session_id' logs/wire_capture.log | sort | uniq -c

# Measure time between chunks
jq -r 'select(.direction=="stream_chunk") | "\(.session_id) \(.timestamp_unix)"' logs/wire_capture.log
```

## Security Notes

### API Key Protection

- Wire capture respects prompt redaction settings
- API keys in prompts are automatically masked
- The `key_name` field shows the environment variable name, not the actual key value
- Example: `"key_name": "OPENAI_API_KEY"` (not the actual key)

### Sensitive Data

- Capture files contain full conversation data
- Store capture files securely with appropriate permissions
- Consider encrypting capture files for sensitive environments
- Use `capture_total_max_bytes` to prevent unbounded disk usage

### Best Practices

1. **Limit Capture Duration**: Only enable capture when debugging
2. **Secure Storage**: Store capture files in protected directories
3. **Regular Cleanup**: Delete old capture files regularly
4. **Access Control**: Restrict access to capture files
5. **Rotation**: Use file rotation to prevent disk exhaustion

## Troubleshooting

### Capture File Not Created

**Problem**: Wire capture file is not being created

**Solutions**:

- Verify the directory exists and is writable
- Check file permissions
- Ensure the path is absolute or relative to the working directory
- Check logs for initialization errors

### Missing Entries

**Problem**: Some requests/responses are not captured

**Solutions**:

- Increase `capture_buffer_size` for high-volume scenarios
- Decrease `capture_flush_interval` for more frequent writes
- Check for disk space issues
- Verify the proxy is not crashing (check logs)

### Large File Sizes

**Problem**: Capture files grow too large

**Solutions**:

- Enable file rotation with `capture_max_bytes`
- Set `capture_total_max_bytes` to limit total disk usage
- Reduce `capture_max_files` to keep fewer rotated files
- Only enable capture when needed

### Performance Impact

**Problem**: Wire capture affects proxy performance

**Solutions**:

- Increase `capture_buffer_size` to reduce I/O frequency
- Increase `capture_flush_interval` for less frequent writes
- Use faster storage (SSD) for capture files
- Consider using CBOR capture for better performance

## Related Features

- [CBOR Capture](cbor-capture.md) - Binary wire capture format for regression testing
- [Troubleshooting](troubleshooting.md) - General troubleshooting guide
- [Security](../security/authentication.md) - Security and authentication features
