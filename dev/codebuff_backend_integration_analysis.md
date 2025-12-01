# Codebuff Backend Integration Analysis

This document analyzes the Codebuff source code to determine what functionality we need to implement in this proxy to support Codebuff as a client.

## Architecture Overview

Codebuff uses a **WebSocket-based architecture** where:

1. The Codebuff client (CLI/IDE extension) connects to the Codebuff backend via WebSocket
2. The backend handles agent orchestration and makes LLM API calls
3. LLM calls are made through the Vercel AI SDK to various providers (OpenAI, Anthropic, Google, OpenRouter, etc.)

## Key Components

### 1. WebSocket Communication (`/ws` endpoint)

The backend exposes a WebSocket server at `/ws` that handles:

- Client connection management
- Message routing via a "Switchboard" pattern
- Topic-based pub/sub for message distribution
- Heartbeat/ping mechanism (60s timeout)

**Message Types:**

- Client -> Server: `identify`, `subscribe`, `unsubscribe`, `ping`, `action`
- Server -> Client: `ack`, `action`

### 2. LLM Integration

Codebuff uses the **Vercel AI SDK** as an abstraction layer for all LLM calls:

**Supported Providers:**

- OpenAI (direct API)
- Anthropic (direct API)
- Google Gemini (direct API)
- OpenRouter (for Claude and other models)
- Vertex AI (finetuned models)
- DeepSeek

**Key Functions:**

- `promptAiSdk()` - Non-streaming LLM calls
- `promptAiSdkStream()` - Streaming LLM calls
- `promptAiSdkStructured()` - Structured output with Zod schemas

**Model Routing Logic:**

```typescript
const modelToAiSDKModel = (model: Model): LanguageModel => {
  if (finetunedVertexModels.includes(model)) return vertexFinetuned(model)
  if (model === 'o3-pro' || model === 'o3') return openai.responses(model)
  if (openaiModels.includes(model)) return openai.languageModel(model)
  // All other models go through OpenRouter
  return openRouterLanguageModel(model)
}
```

### 3. Client Actions (Client -> Server)

The client sends these action types:

- `prompt` - Main LLM request with session state, tool results, model selection
- `read-files-response` - Response to file read requests
- `init` - Initialize session with file context
- `tool-call-response` - Response to tool execution requests
- `cancel-user-input` - Cancel ongoing request
- `mcp-tool-data` - MCP tool metadata response

### 4. Server Actions (Server -> Client)

The server sends these action types:

- `response-chunk` - Streaming LLM response chunks
- `subagent-response-chunk` - Sub-agent output
- `handlesteps-log-chunk` - Logging/debugging info
- `prompt-response` - Final response with session state
- `read-files` - Request files from client
- `tool-call-request` - Request tool execution
- `init-response` - Session initialization response
- `usage-response` - Usage/billing info
- `message-cost-response` - Cost of specific message
- `action-error` / `prompt-error` - Error responses
- `request-reconnect` - Server shutdown signal
- `request-mcp-tool-data` - Request MCP tool metadata

### 5. Tool Call Flow

1. Server sends `tool-call-request` with:
   - `toolName`, `input`, `timeout`, `mcpConfig`
2. Client executes tool locally
3. Client responds with `tool-call-response` containing output
4. Server continues agent execution

### 6. File Access Flow

1. Server sends `read-files` action with file paths
2. Client reads files from local filesystem
3. Client responds with `read-files-response` containing file contents
4. Server uses files in agent context

### 7. Cost Tracking

Every LLM call is tracked with:

- Input/output tokens
- Cache read/creation tokens (Anthropic)
- Cost override (OpenRouter provides actual cost)
- Latency
- Model used
- User/session attribution

## What We Need to Implement

To make this proxy work as a Codebuff backend replacement, we need:

### Phase 1: Core WebSocket Server (MVP)

1. **WebSocket Server** (`/ws` endpoint)
   - Connection management
   - Message parsing/validation (Zod schemas)
   - Heartbeat/ping handling
   - Client session tracking

2. **Action Routing**
   - Parse client actions
   - Route to appropriate handlers
   - Send server actions back to client

3. **LLM Proxy Integration**
   - Intercept `prompt` actions
   - Convert to OpenAI-compatible format
   - Route through existing proxy backends
   - Stream responses back as `response-chunk` actions

### Phase 2: Tool & File Support

4. **Tool Call Orchestration**
   - Send `tool-call-request` to client
   - Wait for `tool-call-response`
   - Continue agent execution

5. **File Access**
   - Send `read-files` requests
   - Handle `read-files-response`
   - Provide files to LLM context

### Phase 3: Advanced Features

6. **Session State Management**
   - Track conversation history
   - Manage tool results
   - Handle session persistence

7. **Usage Tracking**
   - Track token usage
   - Calculate costs
   - Send usage responses

8. **MCP Tool Support**
   - Request MCP tool metadata
   - Handle MCP tool calls

## Technical Considerations

### Message Format Compatibility

Codebuff uses Zod schemas for validation. We need to:

- Implement compatible message schemas
- Validate incoming messages
- Ensure outgoing messages match expected format

### Streaming

Codebuff expects streaming responses:

- Text chunks via `response-chunk` actions
- Reasoning chunks (for thinking models)
- Error chunks

### Authentication

Codebuff uses:

- `authToken` in client actions
- `fingerprintId` for client identification
- Session-based connection tracking

### Error Handling

Codebuff expects specific error formats:

- `action-error` for general errors
- `prompt-error` for LLM errors
- Include remaining balance in errors

## Implementation Strategy

### Minimal MVP Scope

For MVP, implement:

1. WebSocket server with basic message handling
2. `prompt` action -> LLM call conversion
3. Streaming response chunks back to client
4. Basic error handling

**Out of scope for MVP:**

- Tool calls (return empty tool list)
- File access (use only prompt content)
- MCP support
- Usage tracking (return dummy values)
- Session persistence

### Architecture

```text
Codebuff Client (CLI/Extension)
    |
    | WebSocket (/ws)
    v
New WebSocket Handler (Python)
    |
    | Convert prompt action -> OpenAI format
    v
Existing Proxy Backend (Anthropic/OpenAI/etc)
    |
    | Stream response
    v
New WebSocket Handler
    |
    | Convert to response-chunk actions
    v
Codebuff Client
```

## Next Steps

1. Create spec for Codebuff WebSocket backend support
2. Define requirements and acceptance criteria
3. Design the WebSocket handler architecture
4. Implement MVP with streaming support
5. Test with actual Codebuff client
