# Codebuff Protocol Reference

This document provides a complete reference for the Codebuff WebSocket protocol implemented by the LLM Interactive Proxy.

## Protocol Overview

The Codebuff protocol uses JSON messages over WebSocket connections. All communication follows a request-response pattern with acknowledgments.

### Message Structure

All messages are JSON objects with a `type` field that determines the message structure and handling.

### Transaction IDs

Most messages include a `txid` (transaction ID) field for request-response correlation. The server echoes the `txid` in acknowledgment messages.

## Client Message Types

### 1. Identify Message

Establishes the client session ID.

**Format**:

```json
{
  "type": "identify",
  "txid": <integer>,
  "clientSessionId": <string>
}
```

**Fields**:

- `type`: Must be `"identify"`
- `txid`: Transaction ID for correlation
- `clientSessionId`: Unique identifier for this client session

**Response**: `ack` message with `success: true`

**Example**:

```json
{
  "type": "identify",
  "txid": 1,
  "clientSessionId": "session-abc123"
}
```

### 2. Ping Message

Heartbeat message to keep connection alive.

**Format**:

```json
{
  "type": "ping",
  "txid": <integer>
}
```

**Fields**:

- `type`: Must be `"ping"`
- `txid`: Transaction ID for correlation

**Response**: `ack` message with `success: true`

**Example**:

```json
{
  "type": "ping",
  "txid": 42
}
```

**Notes**:

- Clients must send ping messages regularly (recommended: every 30 seconds)
- Connections timeout after `heartbeat_timeout_seconds` without ping
- Default timeout: 60 seconds

### 3. Subscribe Message

Subscribe to one or more topics.

**Format**:

```json
{
  "type": "subscribe",
  "txid": <integer>,
  "topics": [<string>, ...]
}
```

**Fields**:

- `type`: Must be `"subscribe"`
- `txid`: Transaction ID for correlation
- `topics`: Array of topic names to subscribe to

**Response**: `ack` message with `success: true`

**Example**:

```json
{
  "type": "subscribe",
  "txid": 5,
  "topics": ["updates", "notifications", "errors"]
}
```

### 4. Unsubscribe Message

Unsubscribe from one or more topics.

**Format**:

```json
{
  "type": "unsubscribe",
  "txid": <integer>,
  "topics": [<string>, ...]
}
```

**Fields**:

- `type`: Must be `"unsubscribe"`
- `txid`: Transaction ID for correlation
- `topics`: Array of topic names to unsubscribe from

**Response**: `ack` message with `success: true`

**Example**:

```json
{
  "type": "unsubscribe",
  "txid": 6,
  "topics": ["updates"]
}
```

### 5. Action Message

Container for action-specific messages (prompt, init, etc.).

**Format**:

```json
{
  "type": "action",
  "txid": <integer>,
  "data": <action-object>
}
```

**Fields**:

- `type`: Must be `"action"`
- `txid`: Transaction ID for correlation
- `data`: Action-specific object (see Action Types below)

**Response**: `ack` message followed by action-specific responses

## Action Types

### Prompt Action

Request LLM completion.

**Format**:

```json
{
  "type": "prompt",
  "promptId": <string>,
  "prompt": <string | null>,
  "content": <array | null>,
  "promptParams": <object | null>,
  "fingerprintId": <string>,
  "authToken": <string | null>,
  "costMode": <string>,
  "sessionState": <object>,
  "toolResults": <array>,
  "model": <string | null>,
  "repoUrl": <string | null>,
  "agentId": <string | null>
}
```

**Fields**:

- `type`: Must be `"prompt"`
- `promptId`: Unique identifier for this prompt request
- `prompt`: Simple text prompt (alternative to `content`)
- `content`: Structured message content (alternative to `prompt`)
- `promptParams`: Optional parameters for the prompt
- `fingerprintId`: Client fingerprint for usage attribution
- `authToken`: Optional authentication token
- `costMode`: Cost mode (default: `"normal"`)
- `sessionState`: Current session state/conversation history
- `toolResults`: Results from previous tool calls
- `model`: Requested model name (e.g., `"gpt-4"`, `"claude-3-opus"`)
- `repoUrl`: Optional repository URL for context
- `agentId`: Optional agent identifier

**Response Sequence**:

1. `ack` message with `success: true`
2. Multiple `response-chunk` actions (streaming)
3. Final `prompt-response` action (completion)
4. Or `prompt-error` action (on error)

**Example**:

```json
{
  "type": "action",
  "txid": 10,
  "data": {
    "type": "prompt",
    "promptId": "prompt-xyz789",
    "prompt": "Write a Python function to calculate fibonacci numbers",
    "fingerprintId": "client-abc",
    "model": "gpt-4",
    "sessionState": {},
    "toolResults": [],
    "costMode": "normal"
  }
}
```

### Init Action

Initialize session with file context.

**Format**:

```json
{
  "type": "init",
  "fingerprintId": <string>,
  "authToken": <string | null>,
  "fileContext": <object>,
  "repoUrl": <string | null>
}
```

**Fields**:

- `type`: Must be `"init"`
- `fingerprintId`: Client fingerprint for usage attribution
- `authToken`: Optional authentication token
- `fileContext`: File context object containing project files
- `repoUrl`: Optional repository URL

**File Context Structure**:

```json
{
  "files": [
    {
      "path": "relative/path/to/file.py",
      "content": "file contents..."
    }
  ]
}
```

**Response**: `init-response` action

**Example**:

```json
{
  "type": "action",
  "txid": 15,
  "data": {
    "type": "init",
    "fingerprintId": "client-abc",
    "fileContext": {
      "files": [
        {
          "path": "main.py",
          "content": "def main():\n    print('Hello')\n"
        },
        {
          "path": "utils.py",
          "content": "def helper():\n    pass\n"
        }
      ]
    },
    "repoUrl": "https://github.com/user/repo"
  }
}
```

## Server Message Types

### 1. Acknowledgment Message

Acknowledges receipt and validation of client message.

**Format**:

```json
{
  "type": "ack",
  "txid": <integer | null>,
  "success": <boolean>,
  "error": <string | null>
}
```

**Fields**:

- `type`: Always `"ack"`
- `txid`: Transaction ID from client message (null if not applicable)
- `success`: `true` if message was valid and accepted, `false` otherwise
- `error`: Error message if `success` is `false`, null otherwise

**Examples**:

Success:

```json
{
  "type": "ack",
  "txid": 1,
  "success": true,
  "error": null
}
```

Failure:

```json
{
  "type": "ack",
  "txid": 2,
  "success": false,
  "error": "Invalid JSON: Unexpected token at position 42"
}
```

### 2. Server Action Message

Container for server-initiated actions.

**Format**:

```json
{
  "type": "action",
  "data": <action-object>
}
```

**Fields**:

- `type`: Always `"action"`
- `data`: Action-specific object (see Server Action Types below)

## Server Action Types

### Response Chunk Action

Streaming chunk of LLM response.

**Format**:

```json
{
  "type": "response-chunk",
  "userInputId": <string>,
  "chunk": <string>
}
```

**Fields**:

- `type`: Must be `"response-chunk"`
- `userInputId`: Prompt ID from the original request
- `chunk`: Text chunk from the LLM response

**Example**:

```json
{
  "type": "action",
  "data": {
    "type": "response-chunk",
    "userInputId": "prompt-xyz789",
    "chunk": "def fibonacci(n):\n"
  }
}
```

**Notes**:

- Multiple chunks are sent for a single prompt
- Chunks should be concatenated in order to build the complete response
- Final `prompt-response` action signals completion

### Prompt Response Action

Final response after streaming completes.

**Format**:

```json
{
  "type": "prompt-response",
  "promptId": <string>,
  "sessionState": <object>,
  "toolCalls": <array | null>,
  "toolResults": <array | null>,
  "output": <object | null>
}
```

**Fields**:

- `type`: Must be `"prompt-response"`
- `promptId`: Prompt ID from the original request
- `sessionState`: Updated session state after this interaction
- `toolCalls`: Tool calls requested by the LLM (null in MVP)
- `toolResults`: Results from tool execution (null in MVP)
- `output`: Additional output data (null in MVP)

**Example**:

```json
{
  "type": "action",
  "data": {
    "type": "prompt-response",
    "promptId": "prompt-xyz789",
    "sessionState": {
      "messages": [
        {"role": "user", "content": "Write a fibonacci function"},
        {"role": "assistant", "content": "def fibonacci(n):..."}
      ]
    },
    "toolCalls": null,
    "toolResults": null,
    "output": null
  }
}
```

### Prompt Error Action

Error during prompt processing.

**Format**:

```json
{
  "type": "prompt-error",
  "userInputId": <string>,
  "message": <string>,
  "error": <string | null>,
  "remainingBalance": <number | null>
}
```

**Fields**:

- `type`: Must be `"prompt-error"`
- `userInputId`: Prompt ID from the original request
- `message`: User-friendly error message
- `error`: Detailed error information (optional)
- `remainingBalance`: Remaining usage balance (null in MVP)

**Example**:

```json
{
  "type": "action",
  "data": {
    "type": "prompt-error",
    "userInputId": "prompt-xyz789",
    "message": "Backend unavailable",
    "error": "Connection timeout after 30 seconds",
    "remainingBalance": null
  }
}
```

### Init Response Action

Response to init action.

**Format**:

```json
{
  "type": "init-response",
  "message": <string | null>,
  "agentNames": <object | null>,
  "usage": <number>,
  "remainingBalance": <number>,
  "next_quota_reset": <string | null>
}
```

**Fields**:

- `type`: Must be `"init-response"`
- `message`: Optional status message
- `agentNames`: Optional agent name mappings
- `usage`: Usage credits consumed (0 in MVP)
- `remainingBalance`: Remaining balance (unlimited in MVP)
- `next_quota_reset`: Next quota reset time (null in MVP)

**Example**:

```json
{
  "type": "action",
  "data": {
    "type": "init-response",
    "message": "Session initialized successfully",
    "agentNames": null,
    "usage": 0.0,
    "remainingBalance": 999999.0,
    "next_quota_reset": null
  }
}
```

## Error Handling

### Message-Level Errors

Errors in message parsing or validation return an `ack` message with `success: false`:

```json
{
  "type": "ack",
  "txid": 5,
  "success": false,
  "error": "Schema validation failed: 'type' is required"
}
```

### Action-Level Errors

Errors during action processing return action-specific error messages:

**Prompt Errors**:

```json
{
  "type": "action",
  "data": {
    "type": "prompt-error",
    "userInputId": "prompt-123",
    "message": "Model not supported",
    "error": "Model 'gpt-5' is not available",
    "remainingBalance": null
  }
}
```

**Action Errors** (generic):

```json
{
  "type": "action",
  "data": {
    "type": "action-error",
    "message": "Authentication failed",
    "error": "Invalid auth token",
    "remainingBalance": null
  }
}
```

## Connection Lifecycle

### 1. Connection Establishment

```
Client                          Server
  |                               |
  |--- WebSocket Connect -------->|
  |<-- WebSocket Accept ----------|
  |                               |
```

### 2. Session Identification

```
Client                          Server
  |                               |
  |--- identify message --------->|
  |<-- ack (success: true) -------|
  |                               |
```

### 3. Heartbeat Maintenance

```
Client                          Server
  |                               |
  |--- ping message ------------->|
  |<-- ack (success: true) -------|
  |                               |
  |    (30 seconds later)         |
  |--- ping message ------------->|
  |<-- ack (success: true) -------|
  |                               |
```

### 4. Session Initialization (Optional)

```
Client                          Server
  |                               |
  |--- init action -------------->|
  |<-- ack (success: true) -------|
  |<-- init-response action ------|
  |                               |
```

### 5. Prompt Request and Response

```
Client                          Server
  |                               |
  |--- prompt action ------------>|
  |<-- ack (success: true) -------|
  |<-- response-chunk action -----|
  |<-- response-chunk action -----|
  |<-- response-chunk action -----|
  |<-- prompt-response action ----|
  |                               |
```

### 6. Connection Termination

```
Client                          Server
  |                               |
  |--- WebSocket Close ---------->|
  |<-- WebSocket Close -----------|
  |                               |
  |    (Session cleaned up)       |
```

## Best Practices

### Connection Management

1. **Send Regular Pings**: Send ping messages every 30 seconds to prevent timeout
2. **Handle Reconnection**: Implement reconnection logic with exponential backoff
3. **Clean Disconnect**: Close WebSocket properly to allow server cleanup

### Message Handling

1. **Validate Before Sending**: Validate messages against schema before sending
2. **Handle Errors Gracefully**: Check `ack` messages for errors and handle appropriately
3. **Correlate Responses**: Use `txid` and `promptId` to correlate requests and responses

### Streaming Responses

1. **Buffer Chunks**: Accumulate response chunks in order
2. **Handle Completion**: Wait for `prompt-response` before considering request complete
3. **Handle Errors**: Check for `prompt-error` and handle appropriately

### Session Management

1. **Initialize Once**: Send init action once per session
2. **Maintain State**: Track session state across requests
3. **Clean Up**: Close connection when done to free server resources

## Limitations (MVP)

The current implementation has these limitations:

1. **No Tool Calls**: Tool call request/response flow not implemented
2. **No File Access**: Read-files request/response flow not implemented
3. **No Authentication**: Auth tokens accepted but not validated
4. **Dummy Usage**: Usage and balance values are placeholders
5. **No Persistence**: Sessions not persisted across server restarts

These features are planned for future releases.

## Disclaimer

**IMPORTANT LEGAL NOTICE - READ CAREFULLY BEFORE USING THE CODEBUFF-COMPATIBLE BACKEND**

1. **Non-Affiliation**: This project is an independent open-source initiative. It is **not affiliated with, endorsed by, authorized by, or in any way officially connected to** Codebuff or any of their subsidiaries or affiliates. All product and company names are trademarks™ or registered® trademarks of their respective holders. Use of them does not imply any affiliation with or endorsement by them.

2. **No Liability**: The authors, contributors, and maintainers of this project hold **no responsibility or liability** for any consequences arising from the use of this backend in violation of these rules, or for any violations of third-party Terms of Service resulting from such use.

3. **User Responsibility**: You accept full responsibility for ensuring your use of this tool complies with all applicable laws and third-party agreements.

4. **Compliance with Provider Terms**: Users of the Codebuff-compatible backend connector are strictly required to respect all related Terms of Service (ToS) and other agreements with Codebuff and any backend providers. You are solely responsible for verifying that your use of this software is compatible with those agreements.

5. **Indemnification**: You agree to indemnify, defend, and hold harmless the authors and contributors of this project from and against any and all claims, liabilities, damages, losses, or expenses, including legal fees and costs, arising out of or in any way connected with your access to or use of the Codebuff-compatible backend.

**If you do not agree to these terms, do not use the Codebuff-compatible backend interface.**

## See Also

- [Codebuff Backend Feature Guide](features/codebuff-backend.md) - Configuration and usage
- [Configuration Reference](configuration.md) - Complete configuration options
- [Wire Capture](debugging/wire-capture.md) - Debugging WebSocket traffic
