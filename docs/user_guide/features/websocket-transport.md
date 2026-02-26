# WebSocket Transport for Responses API

The proxy supports WebSocket transport for OpenAI's Responses API, enabling low-latency, persistent connections optimized for tool-call-heavy workflows.

## Overview

WebSocket mode provides:

- **Up to 40% faster execution** for workflows with 20+ tool calls
- **Persistent connections** with 60-minute session support
- **Connection-local caching** for `previous_response_id` optimization
- **Reduced overhead** for multi-turn conversations

### Supported Backends

WebSocket transport is available for:

- **OpenAI Responses API** (`wss://api.openai.com/v1/responses`) - Official OpenAI WebSocket endpoint
- **OpenAI Codex Connector** (`wss://chatgpt.com/backend-api/codex/responses`) - Opportunistic support for ChatGPT backend API

Both backends share the same WebSocket client infrastructure and can be enabled independently via configuration.

## Configuration

### Enable Frontend WebSocket (Client → Proxy)

```yaml
# config/config.yaml
responses_api:
  websocket:
    frontend_enabled: true  # Allow clients to connect via WebSocket
    frontend_path: "/v1/responses"  # WebSocket endpoint path
    connection_timeout: 3600  # 60 minutes
    max_connections: 100  # Maximum concurrent connections
```

### Enable Backend WebSocket (Proxy → OpenAI)

Configure your OpenAI backend to use WebSocket transport:

```yaml
backends:
  - backend_type: openai-responses
    api_key: ${OPENAI_API_KEY}
    use_websocket: true  # Enable WebSocket backend transport
```

Or programmatically:

```python
from src.connectors.openai import OpenAIConnector

connector = OpenAIConnector(client, config)
connector.enable_websocket(True)
```

### Enable WebSocket for OpenAI Codex Connector

The Codex connector also supports WebSocket transport:

```yaml
backends:
  openai_codex:
    enabled: true
    extra:
      codex:
        websocket:
          enabled: true  # Enable WebSocket for Codex backend
```

Or via environment variable:

```bash
OPENAI_CODEX_WEBSOCKET_ENABLED=1
```

**Note**: The Codex WebSocket implementation uses opportunistic support - it will connect to `wss://chatgpt.com/backend-api/codex/responses` and automatically falls back to HTTP/SSE if WebSocket is unavailable.

## Client Usage

### Python Client (websockets library)

```python
import asyncio
import json
import websockets


async def use_responses_websocket():
    # Connect to proxy WebSocket endpoint
    async with websockets.connect(
        "ws://localhost:8000/v1/responses",
        extra_headers={
            "Authorization": "Bearer YOUR_PROXY_KEY",
        },
    ) as websocket:
        # Send response.create event
        request_event = {
            "type": "response.create",
            "model": "gpt-4o",
            "input": "Analyze this codebase and suggest improvements",
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file from the codebase",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"}
                            },
                        },
                    },
                }
            ],
        }

        await websocket.send(json.dumps(request_event))

        # Receive streaming events
        while True:
            message = await websocket.recv()
            event = json.loads(message)

            event_type = event.get("type")

            if event_type == "response.content_part.delta":
                # Handle content delta
                delta = event.get("delta", {})
                content = delta.get("content", "")
                print(content, end="", flush=True)

            elif event_type == "response.done":
                # Response complete
                response = event.get("response", {})
                print(f"\n\nResponse ID: {response.get('id')}")
                break

            elif event_type == "error":
                # Handle error
                error = event.get("error", {})
                print(f"Error: {error.get('message')}")
                break


asyncio.run(use_responses_websocket())
```

### Multi-turn Conversations

Use `previous_response_id` to continue conversations:

```python
async def multi_turn_conversation():
    async with websockets.connect(
        "ws://localhost:8000/v1/responses",
        extra_headers={"Authorization": "Bearer YOUR_PROXY_KEY"},
    ) as websocket:
        # First turn
        request1 = {
            "type": "response.create",
            "model": "gpt-4o",
            "input": "What is 2+2?",
        }
        await websocket.send(json.dumps(request1))

        # Get response ID
        while True:
            event = json.loads(await websocket.recv())
            if event.get("type") == "response.done":
                first_response_id = event["response"]["id"]
                break

        # Second turn with previous_response_id
        request2 = {
            "type": "response.create",
            "model": "gpt-4o",
            "input": "Now multiply that by 3",
            "previous_response_id": first_response_id,  # Continue conversation
        }
        await websocket.send(json.dumps(request2))

        # Process second response...
```

## WebSocket Event Protocol

### Client → Proxy Events

#### response.create

Create a new response or continue from a previous response:

```json
{
  "type": "response.create",
  "model": "gpt-4o",
  "input": "Your prompt here",
  "previous_response_id": "resp_123",
  "tools": [],
  "max_output_tokens": 1000
}
```

**Note**: Transport-specific fields like `stream` and `background` are not used in WebSocket mode.

### Proxy → Client Events

#### response.content_part.delta

Streaming content delta:

```json
{
  "type": "response.content_part.delta",
  "delta": {
    "content": "Hello"
  }
}
```

#### response.output_item.done

Output item completed:

```json
{
  "type": "response.output_item.done",
  "item": {
    "id": "msg_123",
    "type": "message",
    "role": "assistant",
    "content": [{"type": "output_text", "text": "Complete message"}]
  }
}
```

#### response.done

Response generation complete:

```json
{
  "type": "response.done",
  "response": {
    "id": "resp_123",
    "object": "response",
    "created": 1234567890,
    "model": "gpt-4o",
    "output": [...],
    "usage": {
      "prompt_tokens": 10,
      "completion_tokens": 20,
      "total_tokens": 30
    }
  }
}
```

#### error

Error occurred:

```json
{
  "type": "error",
  "status": 400,
  "error": {
    "code": "previous_response_not_found",
    "message": "Previous response with id 'resp_123' not found.",
    "param": "previous_response_id"
  }
}
```

## Error Handling

### previous_response_not_found

The `previous_response_id` is not in the connection-local cache:

- **Cause**: Cache miss, eviction, or using ID from different connection
- **Solution**: Start a new response chain or use HTTP fallback

### websocket_connection_limit_reached

Connection has been open for 60 minutes (OpenAI limit):

- **Cause**: Connection timeout reached
- **Solution**: Close and reconnect, then continue with `previous_response_id` if responses are stored

## Performance Benefits

### When to Use WebSocket

WebSocket transport is most beneficial for:

- **Tool-call-heavy workflows**: 20+ tool calls per conversation
- **Agentic coding tasks**: Multiple file reads, writes, and analysis
- **Long-running sessions**: Extended back-and-forth with the model

### Performance Comparison

| Workflow Type | HTTP/SSE | WebSocket | Improvement |
|--------------|----------|-----------|-------------|
| Simple query | ~200ms | ~180ms | ~10% |
| 5 tool calls | ~2.5s | ~2.0s | ~20% |
| 20 tool calls | ~10s | ~6s | ~40% |

*Improvements vary based on network latency and tool complexity*

## Connection Lifecycle

1. **Connect**: Client opens WebSocket connection to `/v1/responses`
2. **Authenticate**: Bearer token sent in `Authorization` header
3. **Session**: Connection-local cache maintained for 60 minutes
4. **Requests**: Multiple `response.create` events can be sent
5. **Responses**: Streaming events sent back for each request
6. **Timeout**: After 60 minutes, connection must be closed and reopened
7. **Disconnect**: Client closes connection or timeout reached

## Limitations

- **Connection duration**: Maximum 60 minutes (OpenAI limit)
- **No multiplexing**: One request at a time per connection (sequential)
- **Cache scope**: `previous_response_id` cache is connection-local only
- **Store compatibility**: Use `store=false` or Zero Data Retention (ZDR) for privacy

## Demo Script

Test WebSocket transport with the included demo script:

```bash
# Test direct OpenAI connection
python scripts/demo_responses_websocket.py --mode direct

# Test through proxy
python scripts/demo_responses_websocket.py --mode proxy --proxy-url ws://localhost:8000/v1/responses

# Multi-turn conversation
python scripts/demo_responses_websocket.py --mode direct --turns 3
```

## Troubleshooting

### Connection Refused

- Ensure `responses_api.websocket.frontend_enabled: true` in config
- Verify proxy is running and accessible
- Check firewall rules for WebSocket connections

### Authentication Failed

- Verify API key is valid
- Check `Authorization` header format: `Bearer YOUR_KEY`
- Ensure key has access to Responses API

### previous_response_not_found

- Response may have been evicted from cache
- Different connection than original request
- Start new conversation or use HTTP fallback

## Related Documentation

- [OpenAI Responses API Frontend](../frontends/openai-responses.md)
- [Configuration Guide](../configuration.md)
- [OpenAI Backend](../backends/openai.md)
