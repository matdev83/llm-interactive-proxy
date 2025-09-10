# Wire Capture Formats Reference

This document describes the different wire capture formats used by the LLM Interactive Proxy across versions.

## Current Format: Buffered JSON Lines

**Implementation**: `BufferedWireCapture` (since v2.x)  
**File Extension**: `.log` or `.jsonl`  
**Performance**: High (buffered I/O, async flushing)

### Format Structure

Each line is a complete JSON object:

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
  "payload": { /* actual request/response data */ },
  "metadata": {
    "client_host": "127.0.0.1",
    "user_agent": "Cline/1.0",
    "request_id": "req_abc123"
  }
}
```

### Field Reference

| Field | Type | Description |
|-------|------|-------------|
| `timestamp_iso` | string | ISO-8601 timestamp with timezone |
| `timestamp_unix` | number | Unix timestamp (seconds since epoch) |
| `direction` | string | `outbound_request`, `inbound_response`, `stream_start`, `stream_chunk`, `stream_end` |
| `source` | string | Source identifier (client or backend) |
| `destination` | string | Destination identifier (client or backend) |
| `session_id` | string\|null | Session identifier if available |
| `backend` | string | Backend name (e.g., "qwen-oauth", "openai") |
| `model` | string | Model name being used |
| `key_name` | string\|null | Environment variable name for API key (not the key itself) |
| `content_type` | string | `json`, `text`, `bytes`, `object` |
| `content_length` | number | Size of payload in bytes |
| `payload` | any | The actual request/response data |
| `metadata` | object | Additional context (client info, request IDs, etc.) |

### Processing Examples

```bash
# Detect format version
head -1 wire_capture.log | jq -r 'if has("timestamp_iso") then "buffered" elif has("timestamp") then "structured" else "human-readable" end'

# Count requests by direction
jq -r '.direction' wire_capture.log | sort | uniq -c

# Extract payloads for specific backend
jq 'select(.backend=="qwen-oauth") | .payload' wire_capture.log

# Calculate average response time (requires matching request/response pairs)
jq -s 'group_by(.session_id) | map(select(length >= 2)) | map({session: .[0].session_id, duration: (.[1].timestamp_unix - .[0].timestamp_unix)}) | map(.duration) | add / length' wire_capture.log
```

## Legacy Formats

### Structured JSON Format

**Implementation**: `StructuredWireCapture` (v1.x)  
**Schema**: Available in `src/core/services/wire_capture_schema.json`

```json
{
  "timestamp": {
    "iso": "2025-01-10T15:58:41.123Z",
    "human_readable": "2025-01-10 15:58:41"
  },
  "communication": {
    "flow": "frontend_to_backend",
    "direction": "request",
    "source": "127.0.0.1",
    "destination": "qwen-oauth"
  },
  "metadata": {
    "session_id": "session-123",
    "backend": "qwen-oauth",
    "model": "qwen3-coder-plus",
    "byte_count": 1247
  },
  "payload": { /* request/response data */ }
}
```

### Human-Readable Format

**Implementation**: `WireCapture` (early versions)  
**Format**: Text with separators

```
----- REQUEST 2025-01-10T15:58:41Z -----
client=127.0.0.1 agent=Cline/1.0 session=session-123 -> backend=qwen-oauth model=qwen3-coder-plus key=primary
{
  "messages": [...],
  "model": "qwen3-coder-plus"
}

----- REPLY 2025-01-10T15:58:42Z -----
client=127.0.0.1 agent=Cline/1.0 session=session-123 -> backend=qwen-oauth model=qwen3-coder-plus
{
  "choices": [...]
}
```

## Migration Between Formats

### Converting Legacy to Current Format

```python
#!/usr/bin/env python3
"""Convert legacy wire capture formats to current buffered format."""

import json
import re
from datetime import datetime

def convert_human_readable_to_buffered(input_file, output_file):
    """Convert human-readable format to buffered JSON lines."""
    with open(input_file, 'r') as f:
        content = f.read()
    
    # Parse human-readable entries
    entries = []
    pattern = r'----- (REQUEST|REPLY) (.*?) -----\n(.*?)\n(.*?)(?=\n----- |$)'
    
    for match in re.finditer(pattern, content, re.DOTALL):
        direction = "outbound_request" if match.group(1) == "REQUEST" else "inbound_response"
        timestamp = match.group(2)
        metadata_line = match.group(3)
        payload_text = match.group(4)
        
        # Parse metadata line
        # Format: client=X agent=Y session=Z -> backend=B model=M key=K
        meta_match = re.match(r'client=(.*?) agent=(.*?) session=(.*?) -> backend=(.*?) model=(.*?)(?: key=(.*))?', metadata_line)
        if not meta_match:
            continue
            
        try:
            payload = json.loads(payload_text)
        except:
            payload = payload_text
        
        entry = {
            "timestamp_iso": timestamp,
            "timestamp_unix": datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp(),
            "direction": direction,
            "source": f"{meta_match.group(1)}({meta_match.group(2)})" if direction == "outbound_request" else meta_match.group(4),
            "destination": meta_match.group(4) if direction == "outbound_request" else f"{meta_match.group(1)}({meta_match.group(2)})",
            "session_id": meta_match.group(3),
            "backend": meta_match.group(4),
            "model": meta_match.group(5),
            "key_name": meta_match.group(6),
            "content_type": "json" if isinstance(payload, dict) else "text",
            "content_length": len(payload_text.encode('utf-8')),
            "payload": payload,
            "metadata": {
                "client_host": meta_match.group(1),
                "user_agent": meta_match.group(2)
            }
        }
        entries.append(entry)
    
    # Write as JSON lines
    with open(output_file, 'w') as f:
        for entry in entries:
            f.write(json.dumps(entry) + '\n')

def convert_structured_to_buffered(input_file, output_file):
    """Convert structured JSON format to buffered format."""
    with open(input_file, 'r') as f_in, open(output_file, 'w') as f_out:
        for line in f_in:
            try:
                old_entry = json.loads(line.strip())
                
                # Map old structure to new structure
                new_entry = {
                    "timestamp_iso": old_entry["timestamp"]["iso"],
                    "timestamp_unix": datetime.fromisoformat(old_entry["timestamp"]["iso"]).timestamp(),
                    "direction": "outbound_request" if old_entry["communication"]["direction"] == "request" else "inbound_response",
                    "source": old_entry["communication"]["source"],
                    "destination": old_entry["communication"]["destination"],
                    "session_id": old_entry["metadata"]["session_id"],
                    "backend": old_entry["metadata"]["backend"],
                    "model": old_entry["metadata"]["model"],
                    "key_name": old_entry["metadata"].get("key_name"),
                    "content_type": "json",
                    "content_length": old_entry["metadata"]["byte_count"],
                    "payload": old_entry["payload"],
                    "metadata": {
                        "agent": old_entry["metadata"].get("agent")
                    }
                }
                
                f_out.write(json.dumps(new_entry) + '\n')
                
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Skipping invalid entry: {e}")
                continue

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 4:
        print("Usage: python convert_wire_capture.py <format> <input_file> <output_file>")
        print("Formats: human-readable, structured")
        sys.exit(1)
    
    format_type, input_file, output_file = sys.argv[1:4]
    
    if format_type == "human-readable":
        convert_human_readable_to_buffered(input_file, output_file)
    elif format_type == "structured":
        convert_structured_to_buffered(input_file, output_file)
    else:
        print(f"Unknown format: {format_type}")
        sys.exit(1)
    
    print(f"Converted {input_file} to {output_file}")
```

## Format Detection

```bash
# Detect wire capture format
detect_format() {
    local file="$1"
    if head -1 "$file" | grep -q "^{"; then
        if head -1 "$file" | jq -e 'has("timestamp_iso")' >/dev/null 2>&1; then
            echo "buffered"
        elif head -1 "$file" | jq -e 'has("timestamp")' >/dev/null 2>&1; then
            echo "structured"
        else
            echo "unknown-json"
        fi
    elif head -1 "$file" | grep -q "^-----"; then
        echo "human-readable"
    else
        echo "unknown"
    fi
}

format=$(detect_format wire_capture.log)
echo "Detected format: $format"
```

## Best Practices

1. **Always check format** before processing wire capture files
2. **Use consistent file extensions**: `.jsonl` for JSON Lines formats, `.log` for human-readable
3. **Include format version** in file headers for future compatibility
4. **Test processing scripts** with sample data from each format
5. **Document format changes** in migration notes when upgrading

## Problem discovery and moving forward

You've identified a critical inconsistency! Looking at the grep results, I can see there's a mismatch in the  service registration: 
🚨 Current State: Inconsistent Service Registration

Active Service Registration (What's Actually Used):
• ✅ src/core/app/stages/core_services.py → BufferedWireCaptur (NEW)

Legacy Service Registration (Still Present):
• ❌ src/core/di/services.py → StructuredWireCapture (OLD)

The Problem                                                    │

We have two different service registrations for the same nterface:
1 core_services.py (Stage-based registration) → BufferedWireCapture
2 di/services.py (Legacy DI registration) → StructuredWireCapture                                               

This means depending on which registration system is used, you could get different wire capture implementations  with different formats!

Current File Formats

Yes, we still have three different formats:

│   Implementation          Format                Status      File Location                                        │
│  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━                  │
│   BufferedWireCapture     Flat JSON Lines       ✅ Active   buffered_wire_capture_service.py                     │
│   StructuredWireCapture   Nested JSON Lines     ❌ Legacy   structured_wire_capture_service.py                   │
│   WireCapture             Human-readable text   ❌ Legacy   wire_capture_service.py                              │
│                                                                                                               

Immediate Action Needed

The legacy service registration should be removed to ensure consistency:

```python
# In src/core/di/services.py - REMOVE these lines:                                                              
from src.core.services.structured_wire_capture_service import StructuredWireCapture
def _wire_capture_factory(provider: IServiceProvider) -> StructuredWireCapture:
    cfg = provider.get_required_service(AppConfig)
    return StructuredWireCapture(cfg)

_add_singleton(StructuredWireCapture, implementation_factory=_wire_capture_factory)                             ```

Recommendation                                                  
1 Remove legacy service registration from di/services.py
2 Keep only BufferedWireCapture as the active implementation│
3 Move legacy implementations to a legacy/ folder for reference
4 Update documentation to clarify that only one format is currently active. This would eliminate the confusion and ensure consistent wire capture format across all usage scenarios.