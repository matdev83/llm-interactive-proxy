# Codebuff Backend Compatibility

The LLM Interactive Proxy includes a WebSocket server that implements the Codebuff protocol, allowing Codebuff clients to connect and route their LLM requests through the proxy's backend infrastructure.

## Overview

Codebuff is a coding agent platform that uses AI models to assist with software development. The proxy's Codebuff backend compatibility feature enables:

- WebSocket-based communication using the Codebuff protocol
- Session management with heartbeat monitoring
- Streaming LLM responses
- File context initialization
- Topic-based subscription management
- Integration with all existing proxy backends (OpenAI, Anthropic, Gemini, etc.)

## Configuration

### Basic Setup

Add the following to your `config.yaml`:

```yaml
codebuff:
  enabled: true  # Enable the Codebuff WebSocket server
  websocket_path: "/ws"  # WebSocket endpoint path
  heartbeat_timeout_seconds: 60  # Client heartbeat timeout
  session_cleanup_hours: 1  # Inactive session cleanup interval
  max_connections: 1000  # Maximum concurrent connections
  max_message_size_bytes: 1048576  # Maximum message size (1MB)
```

### Configuration Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable/disable the Codebuff WebSocket server |
| `websocket_path` | string | `"/ws"` | WebSocket endpoint path |
| `heartbeat_timeout_seconds` | integer | `60` | Seconds without ping before connection timeout |
| `session_cleanup_hours` | integer | `1` | Hours of inactivity before session cleanup |
| `max_connections` | integer | `1000` | Maximum concurrent WebSocket connections |
| `max_message_size_bytes` | integer | `1048576` | Maximum message size in bytes (1MB) |

## Usage

### Starting the Server

Start the proxy with Codebuff enabled:

```bash
# Using configuration file
python -m src.core.cli --config config/my_config.yaml

# Or with CLI parameters
python -m src.core.cli --default-backend openai:gpt-4o
```

The WebSocket server will be available at `ws://localhost:8000/ws` (or your configured host/port).

### Connecting a Codebuff Client

Configure your Codebuff client to connect to the proxy:

```bash
# Example Codebuff client configuration
codebuff --backend-url ws://localhost:8000/ws
```

## Usage Examples

- **Route all Codebuff traffic through the proxy**: Start the proxy with `codebuff.enabled: true` and point your Codebuff client to `ws://localhost:8000/ws`.
- **Force a specific backend/model**: Configure `default_backend` in your config file (for example `openai:gpt-4o`) so every Codebuff prompt uses the selected provider.
- **Enable debugging captures**: Start the proxy with wire capture enabled and inspect traffic using `scripts/inspect_cbor_capture.py` to debug model/tool issues.
- **Tighten limits**: Adjust `heartbeat_timeout_seconds` and `max_message_size_bytes` to align with your infrastructure constraints.

## Use Cases

- **Standardizing enterprise access**: Keep Codebuff clients unmodified while enforcing backend routing, quotas, and audit logging centrally.
- **Tooling validation**: Safely test new tool-call behaviors (like file editing) by capturing and replaying streams without touching client code.
- **Session-aware assistance**: Preserve file context and conversation history for multi-turn coding flows, even when Codebuff reconnects.
- **Compliance and observability**: Capture usage, logs, and wire data in one place to support governance and debugging.

## Protocol Overview

The Codebuff protocol uses JSON messages over WebSocket. All messages follow a structured format with type-based routing.

### Connection Flow

1. **Connect**: Client establishes WebSocket connection to `/ws`
2. **Identify**: Client sends `identify` message with session ID
3. **Ping**: Client sends periodic `ping` messages for heartbeat
4. **Actions**: Client sends `action` messages (prompt, init, subscribe, etc.)
5. **Responses**: Server sends `ack` and `action` responses
6. **Disconnect**: Connection closes, session cleaned up

### Message Types

#### Client Messages

**Identify Message**

```json
{
  "type": "identify",
  "txid": 1,
  "clientSessionId": "session-123"
}
```

**Ping Message**

```json
{
  "type": "ping",
  "txid": 2
}
```

**Prompt Action**

```json
{
  "type": "action",
  "txid": 3,
  "data": {
    "type": "prompt",
    "promptId": "prompt-456",
    "prompt": "Write a hello world function",
    "fingerprintId": "client-fingerprint",
    "model": "gpt-4",
    "sessionState": {},
    "toolResults": []
  }
}
```

**Init Action**

```json
{
  "type": "action",
  "txid": 4,
  "data": {
    "type": "init",
    "fingerprintId": "client-fingerprint",
    "fileContext": {
      "files": [
        {"path": "main.py", "content": "..."}
      ]
    }
  }
}
```

**Subscribe/Unsubscribe**

```json
{
  "type": "subscribe",
  "txid": 5,
  "topics": ["updates", "notifications"]
}
```

#### Server Messages

**Acknowledgment**

```json
{
  "type": "ack",
  "txid": 1,
  "success": true,
  "error": null
}
```

**Response Chunk (Streaming)**

```json
{
  "type": "action",
  "data": {
    "type": "response-chunk",
    "userInputId": "prompt-456",
    "chunk": "def hello_world():\n"
  }
}
```

**Prompt Response (Final)**

```json
{
  "type": "action",
  "data": {
    "type": "prompt-response",
    "promptId": "prompt-456",
    "sessionState": {},
    "toolCalls": null,
    "toolResults": null,
    "output": null
  }
}
```

**Error Response**

```json
{
  "type": "action",
  "data": {
    "type": "prompt-error",
    "userInputId": "prompt-456",
    "message": "Backend unavailable",
    "error": "Connection timeout",
    "remainingBalance": null
  }
}
```

## Features

### Session Management

Each WebSocket connection maintains a session with:

- Unique session ID
- Conversation history
- File context (from init action)
- Subscription topics
- Last-seen timestamp for heartbeat monitoring

Sessions are automatically cleaned up after the configured inactivity period.

### Heartbeat Monitoring

Clients must send periodic `ping` messages to keep the connection alive. If no ping is received within `heartbeat_timeout_seconds`, the connection is terminated and the session is cleaned up.

### Streaming Responses

LLM responses are streamed in real-time as `response-chunk` actions. Each chunk includes:

- The user input ID for correlation
- A text chunk from the LLM response

When streaming completes, a final `prompt-response` action is sent with the complete session state.

### File Context

Clients can initialize a session with file context using the `init` action. This context is stored in the session and made available for subsequent prompt actions, allowing the LLM to understand the codebase.

### Topic Subscriptions

Clients can subscribe to topics to receive targeted messages. The subscription system supports:

- Multiple topics per client
- Dynamic subscribe/unsubscribe
- Automatic cleanup on disconnect

### Backend Integration

The Codebuff backend integrates seamlessly with the proxy's existing infrastructure:

- **Backend Factory**: Routes requests to appropriate backends based on model name
- **Format Conversion**: Converts between Codebuff and OpenAI message formats
- **Middleware**: Applies all existing response middleware
- **Accounting**: Tracks usage and attributes costs to fingerprint IDs
- **Error Handling**: Uses the proxy's exception hierarchy

## Error Handling

### Connection Errors

- **Heartbeat Timeout**: Connection terminated after `heartbeat_timeout_seconds` without ping
- **Max Connections**: New connections rejected when `max_connections` is reached
- **Message Size**: Messages exceeding `max_message_size_bytes` are rejected

### Message Errors

- **JSON Parsing**: Invalid JSON returns `ack` with `success=false`
- **Schema Validation**: Invalid message structure returns `ack` with error details
- **Unknown Message Type**: Unrecognized types return `ack` with error

### LLM Request Errors

- **Backend Unavailable**: Returns `prompt-error` with backend status
- **Unsupported Model**: Returns `prompt-error` indicating model not supported
- **Streaming Error**: Returns `prompt-error` with error details
- **Timeout**: Returns `prompt-error` after request timeout

## Monitoring

### Logging

The Codebuff backend logs:

- Connection events (connect, disconnect)
- Message types and session IDs
- Errors with full context
- Heartbeat timeouts

Sensitive information (auth tokens, full message contents) is never logged.

### Metrics

Key metrics to monitor:

- Active WebSocket connections
- Messages per second
- Average response time
- Error rate
- Session count
- Memory usage per connection

## Security Considerations

### Authentication (MVP)

In the current MVP implementation:

- Auth tokens are accepted but not validated
- Fingerprint IDs are tracked for attribution
- Usage values are dummy placeholders

Future versions will add:

- Token validation against user database
- Rate limiting per user
- Real usage tracking and billing

### Input Validation

All inputs are validated:

- JSON schema validation for all messages
- Sanitization of user-provided strings
- Model name validation against allowed list
- Message size limits enforced

### Logging Security

Logs exclude:

- Auth tokens
- Full message contents (only types and IDs logged)
- Sensitive file contents
- User credentials

## Troubleshooting

### Connection Issues

**Problem**: Client cannot connect to WebSocket

**Solutions**:

- Verify `codebuff.enabled: true` in configuration
- Check that proxy is running and accessible
- Verify WebSocket path matches client configuration
- Check firewall rules allow WebSocket connections

### Heartbeat Timeouts

**Problem**: Connections frequently timeout

**Solutions**:

- Increase `heartbeat_timeout_seconds` in configuration
- Verify client is sending ping messages regularly
- Check network stability between client and server

### Message Validation Errors

**Problem**: Messages rejected with validation errors

**Solutions**:

- Verify message format matches protocol specification
- Check JSON is valid and properly formatted
- Ensure all required fields are present
- Review error message for specific validation failures

### Backend Errors

**Problem**: Prompts fail with backend errors

**Solutions**:

- Verify backend is configured and accessible
- Check API keys are set correctly
- Ensure model name is supported by backend
- Review backend-specific documentation

## Limitations (MVP)

The current MVP implementation has the following limitations:

**Not Implemented**:

- Tool call support (tool-call-request/response flow)
- File access support (read-files request/response)
- MCP tool support
- Real authentication and authorization
- Real usage tracking and billing
- Session persistence across restarts
- WebSocket compression

These features are planned for future releases.

## Examples

### Complete Connection Flow

```python
import asyncio
import websockets
import json

async def codebuff_client():
    uri = "ws://localhost:8000/ws"
    
    async with websockets.connect(uri) as websocket:
        # 1. Identify
        await websocket.send(json.dumps({
            "type": "identify",
            "txid": 1,
            "clientSessionId": "my-session"
        }))
        response = await websocket.recv()
        print(f"Identify: {response}")
        
        # 2. Initialize with file context
        await websocket.send(json.dumps({
            "type": "action",
            "txid": 2,
            "data": {
                "type": "init",
                "fingerprintId": "my-client",
                "fileContext": {
                    "files": [{"path": "main.py", "content": "# My code"}]
                }
            }
        }))
        response = await websocket.recv()
        print(f"Init: {response}")
        
        # 3. Send prompt
        await websocket.send(json.dumps({
            "type": "action",
            "txid": 3,
            "data": {
                "type": "prompt",
                "promptId": "prompt-1",
                "prompt": "Write a hello world function",
                "fingerprintId": "my-client",
                "model": "gpt-4",
                "sessionState": {},
                "toolResults": []
            }
        }))
        
        # 4. Receive streaming response
        while True:
            response = await websocket.recv()
            data = json.loads(response)
            
            if data["type"] == "action":
                action_type = data["data"]["type"]
                
                if action_type == "response-chunk":
                    print(data["data"]["chunk"], end="", flush=True)
                elif action_type == "prompt-response":
                    print("\nComplete!")
                    break
                elif action_type == "prompt-error":
                    print(f"\nError: {data['data']['message']}")
                    break

asyncio.run(codebuff_client())
```

## Disclaimer

**IMPORTANT LEGAL NOTICE - READ CAREFULLY BEFORE USING THE CODEBUFF-COMPATIBLE BACKEND**

1. **Non-Affiliation**: This project is an independent open-source initiative. It is **not affiliated with, endorsed by, authorized by, or in any way officially connected to** Codebuff or any of their subsidiaries or affiliates. All product and company names are trademarks™ or registered® trademarks of their respective holders. Use of them does not imply any affiliation with or endorsement by them.

2. **No Liability**: The authors, contributors, and maintainers of this project hold **no responsibility or liability** for any consequences arising from the use of this backend in violation of these rules, or for any violations of third-party Terms of Service resulting from such use.

3. **User Responsibility**: You accept full responsibility for ensuring your use of this tool complies with all applicable laws and third-party agreements.

4. **Compliance with Provider Terms**: Users of the Codebuff-compatible backend connector are strictly required to respect all related Terms of Service (ToS) and other agreements with Codebuff and any backend providers. You are solely responsible for verifying that your use of this software is compatible with those agreements.

5. **Indemnification**: You agree to indemnify, defend, and hold harmless the authors and contributors of this project from and against any and all claims, liabilities, damages, losses, or expenses, including legal fees and costs, arising out of or in any way connected with your access to or use of the Codebuff-compatible backend.

**If you do not agree to these terms, do not use the Codebuff-compatible backend interface.**

## See Also

- [Configuration Guide](../configuration.md) - Complete configuration reference
- [Backend Overview](../backends/overview.md) - Available backends
- [Wire Capture](../debugging/wire-capture.md) - Debugging WebSocket traffic
- [Session Management](./session-management.md) - Session configuration
