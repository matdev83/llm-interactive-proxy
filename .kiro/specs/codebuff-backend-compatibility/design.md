# Design Document

## Overview

This design document specifies the architecture and implementation approach for adding Codebuff backend compatibility to the LLM proxy server. The implementation will add a WebSocket server endpoint that speaks the Codebuff protocol, allowing Codebuff clients to connect and route their LLM requests through the proxy's existing backend infrastructure.

The design follows an MVP approach, focusing on core functionality (WebSocket communication, prompt handling, and streaming responses) while deferring advanced features (tool calls, file access, MCP support) to future iterations.

## Architecture

### High-Level Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                     Codebuff Client                              │
│                  (CLI / IDE Extension)                           │
└────────────────────────────┬────────────────────────────────────┘
                             │ WebSocket (/ws)
                             │ JSON Messages
                             v
┌─────────────────────────────────────────────────────────────────┐
│                  WebSocket Handler (New)                         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Connection Manager                                       │  │
│  │  - Session tracking                                       │  │
│  │  - Heartbeat monitoring                                   │  │
│  │  - Subscription management                                │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Message Router                                           │  │
│  │  - Parse & validate messages                             │  │
│  │  - Route to action handlers                              │  │
│  │  - Send responses                                         │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Action Handlers                                          │  │
│  │  - PromptHandler: LLM requests                           │  │
│  │  - InitHandler: Session initialization                   │  │
│  │  - SubscriptionHandler: Topic management                 │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────┘
                             │ Convert to OpenAI format
                             v
┌─────────────────────────────────────────────────────────────────┐
│              Existing Proxy Infrastructure                       │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Backend Factory                                          │  │
│  │  - Select backend by model                               │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Backend Connectors                                       │  │
│  │  - Anthropic, OpenAI, Gemini, etc.                       │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Response Middleware                                      │  │
│  │  - Stream processing                                      │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────┘
                             │ Stream response
                             v
┌─────────────────────────────────────────────────────────────────┐
│                  WebSocket Handler (New)                         │
│  - Convert to response-chunk actions                            │
│  - Send via WebSocket                                           │
└─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

**WebSocket Server**
- Accept connections on `/ws` endpoint
- Manage WebSocket lifecycle (connect, disconnect, error)
- Integrate with existing HTTP server infrastructure

**Connection Manager**
- Track active WebSocket connections
- Maintain session state per connection
- Monitor heartbeats and terminate stale connections
- Clean up resources on disconnect

**Message Router**
- Parse incoming JSON messages
- Validate against Codebuff message schemas
- Route to appropriate action handlers
- Send acknowledgments and responses

**Action Handlers**
- PromptHandler: Process LLM requests, convert formats, stream responses
- InitHandler: Initialize sessions with file context
- SubscriptionHandler: Manage topic subscriptions

**Format Converter**
- Convert Codebuff message format to OpenAI format
- Convert OpenAI responses to Codebuff response-chunk format
- Handle model name mapping

## Components and Interfaces

### WebSocket Server Module

```python
class CodebuffWebSocketServer:
    """WebSocket server for Codebuff protocol."""
    
    def __init__(
        self,
        app: FastAPI,
        connection_manager: ConnectionManager,
        message_router: MessageRouter,
        logger: Logger
    ):
        """Initialize WebSocket server."""
        
    async def handle_connection(self, websocket: WebSocket) -> None:
        """Handle a WebSocket connection lifecycle."""
        
    async def send_message(
        self,
        websocket: WebSocket,
        message: ServerMessage
    ) -> None:
        """Send a message to the client."""
```

### Connection Manager

```python
@dataclass
class ClientSession:
    """Session data for a connected client."""
    session_id: str
    fingerprint_id: Optional[str]
    auth_token: Optional[str]
    last_seen: datetime
    subscriptions: Set[str]
    file_context: CodebuffJsonObject | None
    conversation_history: list[CodebuffJsonObject]

class ConnectionManager:
    """Manages WebSocket connections and sessions."""
    
    def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Register a new connection."""
        
    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a connection and clean up session."""
        
    def get_session(self, websocket: WebSocket) -> Optional[ClientSession]:
        """Get session data for a connection."""
        
    def update_last_seen(self, websocket: WebSocket) -> None:
        """Update last-seen timestamp for heartbeat."""
        
    def subscribe(self, websocket: WebSocket, topics: List[str]) -> None:
        """Add subscriptions for a connection."""
        
    def unsubscribe(self, websocket: WebSocket, topics: List[str]) -> None:
        """Remove subscriptions for a connection."""
        
    def get_subscribers(self, topic: str) -> List[WebSocket]:
        """Get all connections subscribed to a topic."""
        
    async def cleanup_stale_connections(self) -> None:
        """Terminate connections that haven't pinged recently."""
```

### Message Router

```python
class MessageRouter:
    """Routes incoming messages to appropriate handlers."""
    
    def __init__(
        self,
        prompt_handler: PromptHandler,
        init_handler: InitHandler,
        subscription_handler: SubscriptionHandler,
        logger: Logger
    ):
        """Initialize router with handlers."""
        
    async def route_message(
        self,
        websocket: WebSocket,
        message: ClientMessage
    ) -> ServerMessage:
        """Parse, validate, and route a message."""
        
    def validate_message(self, raw_message: object) -> ClientMessage:
        """Validate and parse the raw message into a typed contract."""
```

### Action Handlers

```python
class PromptHandler:
    """Handles prompt actions (LLM requests)."""
    
    def __init__(
        self,
        backend_factory: BackendFactory,
        format_converter: FormatConverter,
        connection_manager: ConnectionManager,
        logger: Logger
    ):
        """Initialize prompt handler."""
        
    async def handle_prompt(
        self,
        websocket: WebSocket,
        action: PromptAction
    ) -> None:
        """Process a prompt action and stream response."""

class InitHandler:
    """Handles init actions (session initialization)."""
    
    async def handle_init(
        self,
        websocket: WebSocket,
        action: InitAction
    ) -> InitResponse:
        """Initialize a session with file context."""

class SubscriptionHandler:
    """Handles subscribe/unsubscribe actions."""
    
    async def handle_subscribe(
        self,
        websocket: WebSocket,
        topics: List[str]
    ) -> None:
        """Add subscriptions for a connection."""
        
    async def handle_unsubscribe(
        self,
        websocket: WebSocket,
        topics: List[str]
    ) -> None:
        """Remove subscriptions for a connection."""
```

### Format Converter

```python
class FormatConverter:
    """Converts between Codebuff and OpenAI message formats."""
    
    def codebuff_to_openai(
        self,
        messages: list[CodebuffJsonObject],
        session_state: CodebuffJsonObject
    ) -> list[CodebuffJsonObject]:
        """Convert Codebuff messages to OpenAI format."""
        
    def create_response_chunk(
        self,
        user_input_id: str,
        text: str
    ) -> CodebuffJsonObject:
        """Create a response-chunk action."""
        
    def create_prompt_response(
        self,
        prompt_id: str,
        session_state: CodebuffJsonObject
    ) -> CodebuffJsonObject:
        """Create a prompt-response action."""
        
    def create_error_response(
        self,
        user_input_id: str,
        error_message: str
    ) -> CodebuffJsonObject:
        """Create a prompt-error action."""
```

## Data Models

### Message Schemas

```python
# Client Messages
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CodebuffJsonObject(BaseModel):
    """Typed JSON-object envelope for Codebuff protocol payload fragments."""

    model_config = ConfigDict(extra="allow")


class AgentNameEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    agentName: str


class AgentNames(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: list[AgentNameEntry] = Field(default_factory=list)

class IdentifyMessage(BaseModel):
    type: Literal["identify"]
    txid: int
    clientSessionId: str

class PingMessage(BaseModel):
    type: Literal["ping"]
    txid: int

class SubscribeMessage(BaseModel):
    type: Literal["subscribe"]
    txid: int
    topics: List[str]

class UnsubscribeMessage(BaseModel):
    type: Literal["unsubscribe"]
    txid: int
    topics: List[str]

class PromptAction(BaseModel):
    type: Literal["prompt"]
    promptId: str
    prompt: Optional[str]
    content: list[CodebuffJsonObject] | None = None
    promptParams: CodebuffJsonObject | None = None
    fingerprintId: str
    authToken: Optional[str]
    costMode: str = "normal"
    sessionState: CodebuffJsonObject
    toolResults: list[CodebuffJsonObject]
    model: Optional[str]
    repoUrl: Optional[str]
    agentId: Optional[str]

class InitAction(BaseModel):
    type: Literal["init"]
    fingerprintId: str
    authToken: Optional[str]
    fileContext: CodebuffJsonObject
    repoUrl: Optional[str]

class ActionMessage(BaseModel):
    type: Literal["action"]
    txid: int
    data: PromptAction | InitAction = Field(discriminator="type")

ClientMessage = (
    IdentifyMessage | PingMessage | SubscribeMessage | UnsubscribeMessage | ActionMessage
)

# Server Messages
class AckMessage(BaseModel):
    type: Literal["ack"]
    txid: Optional[int]
    success: bool
    error: Optional[str]

class ResponseChunkAction(BaseModel):
    type: Literal["response-chunk"]
    userInputId: str
    chunk: str

class PromptResponseAction(BaseModel):
    type: Literal["prompt-response"]
    promptId: str
    sessionState: CodebuffJsonObject
    toolCalls: list[CodebuffJsonObject] | None = None
    toolResults: list[CodebuffJsonObject] | None = None
    output: CodebuffJsonObject | None = None

class PromptErrorAction(BaseModel):
    type: Literal["prompt-error"]
    userInputId: str
    message: str
    error: Optional[str]
    remainingBalance: Optional[float]

class InitResponseAction(BaseModel):
    type: Literal["init-response"]
    message: Optional[str]
    agentNames: AgentNames | None = None
    usage: float
    remainingBalance: float
    next_quota_reset: Optional[datetime]

class ServerActionMessage(BaseModel):
    type: Literal["action"]
    data: (
        ResponseChunkAction
        | PromptResponseAction
        | PromptErrorAction
        | InitResponseAction
    ) = Field(discriminator="type")

ServerMessage = AckMessage | ServerActionMessage
```

### Session State

```python
@dataclass
class SessionState:
    """State maintained for each client session."""
    session_id: str
    fingerprint_id: Optional[str]
    auth_token: Optional[str]
    created_at: datetime
    last_seen: datetime
    subscriptions: Set[str]
    file_context: CodebuffJsonObject | None
    conversation_history: list[CodebuffJsonObject]
    active_requests: list[CodebuffJsonObject]  # request states (prompt_id embedded in payload)
```

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system-essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*


### Connection Management Properties

Property 1: Connection tracking
*For any* WebSocket connection to `/ws`, the system should create a session entry and track the connection
**Validates: Requirements 1.1**

Property 2: Session ID association
*For any* identify message with a session ID, the system should store that ID and associate it with the WebSocket connection
**Validates: Requirements 1.2**

Property 3: Heartbeat timestamp updates
*For any* ping message from a connection, the system should update the last-seen timestamp for that connection
**Validates: Requirements 1.3**

Property 4: Session cleanup on disconnect
*For any* disconnecting client, the system should remove the session state and connection from tracking
**Validates: Requirements 1.5**

### Message Processing Properties

Property 5: Message extraction
*For any* valid prompt action, the system should successfully extract conversation messages and model selection
**Validates: Requirements 2.1**

Property 6: Format conversion validity
*For any* Codebuff message format, converting to OpenAI format should produce valid OpenAI-compatible messages
**Validates: Requirements 2.2**

Property 7: Backend routing
*For any* model name in a prompt, the system should route the request to the appropriate backend connector
**Validates: Requirements 2.3**

Property 8: JSON parsing
*For any* valid JSON string received as a message, the system should successfully parse it
**Validates: Requirements 6.1**

Property 9: Schema validation
*For any* parsed message, the system should validate it against the expected Codebuff message schema
**Validates: Requirements 6.3**

Property 10: Valid message acknowledgment
*For any* valid message, the system should send an ack message with success=true
**Validates: Requirements 6.5**

### Streaming Properties

Property 11: Chunk conversion
*For any* stream of text chunks from the backend, each chunk should be converted to a response-chunk action
**Validates: Requirements 3.1**

Property 12: User input ID correlation
*For any* request with a user input ID, all response chunks should include that same user input ID
**Validates: Requirements 3.2**

Property 13: Cancellation cleanup
*For any* active streaming request, canceling it should stop the stream and clean up the request state
**Validates: Requirements 3.5**

### Authentication Properties

Property 14: Token validation
*For any* prompt or init action with an auth token, the system should validate that token
**Validates: Requirements 4.1**

Property 15: Fingerprint association
*For any* action with a fingerprint ID, the system should associate that ID with the client session
**Validates: Requirements 4.4**

Property 16: Cost attribution
*For any* usage event, the system should attribute costs to the fingerprint ID or session ID
**Validates: Requirements 4.5**

### Session Management Properties

Property 17: File context storage
*For any* init action with file context, the system should store that context in the session
**Validates: Requirements 5.1**

Property 18: File context persistence
*For any* session with stored file context, subsequent prompt actions should have access to that context
**Validates: Requirements 5.3**

### Concurrency Properties

Property 19: Session isolation
*For any* set of connected clients, each client's session state should be independent and not affect others
**Validates: Requirements 7.1**

Property 20: Operation isolation
*For any* client operation (prompt, init, etc.), it should not affect other clients' sessions
**Validates: Requirements 7.2**

Property 21: Disconnect isolation
*For any* client disconnecting, other active connections should remain unaffected
**Validates: Requirements 7.3**

### Logging Properties

Property 22: Connection logging
*For any* client connection, a log entry should be created with the session ID
**Validates: Requirements 8.1**

Property 23: Message logging
*For any* received message, a log entry should be created with the message type and session ID
**Validates: Requirements 8.2**

Property 24: Error logging
*For any* error that occurs, a log entry should be created with full context including session ID and error details
**Validates: Requirements 8.3**

Property 25: Disconnect logging
*For any* client disconnection, a log entry should be created
**Validates: Requirements 8.4**

Property 26: Sensitive data exclusion
*For any* log entry, it should not contain sensitive information like auth tokens or full message contents
**Validates: Requirements 8.5**

### Subscription Properties

Property 27: Subscription addition
*For any* subscribe action with topics, the system should add the client to those topics
**Validates: Requirements 9.1**

Property 28: Subscription removal
*For any* unsubscribe action with topics, the system should remove the client from those topics
**Validates: Requirements 9.2**

Property 29: Topic message distribution
*For any* message published to a topic, all clients subscribed to that topic should receive it
**Validates: Requirements 9.3**

Property 30: Subscription cleanup
*For any* disconnecting client, all subscriptions for that client should be removed
**Validates: Requirements 9.4**

### Integration Properties

Property 31: Backend factory usage
*For any* LLM request, the system should use the existing backend factory to select the appropriate connector
**Validates: Requirements 10.1**

Property 32: Middleware application
*For any* response from a backend, the system should apply existing response middleware
**Validates: Requirements 10.2**

Property 33: Accounting integration
*For any* usage event, the system should use the existing accounting utilities
**Validates: Requirements 10.3**

Property 34: Exception hierarchy usage
*For any* error that occurs, the system should use exceptions from the existing exception hierarchy
**Validates: Requirements 10.4**

## Error Handling

### Error Categories

**Connection Errors**
- WebSocket connection failures
- Heartbeat timeout
- Unexpected disconnections

**Message Errors**
- JSON parsing failures
- Schema validation failures
- Unknown message types

**Authentication Errors**
- Invalid auth tokens (future)
- Missing required credentials (future)

**LLM Request Errors**
- Backend unavailable
- Unsupported model
- Streaming errors
- Timeout errors

**Session Errors**
- Session not found
- Invalid session state
- Concurrent modification

### Error Response Format

All errors should be sent to the client in the appropriate format:

**For message-level errors:**
```json
{
  "type": "ack",
  "txid": 123,
  "success": false,
  "error": "Error message"
}
```

**For action errors:**
```json
{
  "type": "action",
  "data": {
    "type": "action-error",
    "message": "Error message",
    "error": "Detailed error",
    "remainingBalance": 0.0
  }
}
```

**For prompt errors:**
```json
{
  "type": "action",
  "data": {
    "type": "prompt-error",
    "userInputId": "prompt-123",
    "message": "Error message",
    "error": "Detailed error",
    "remainingBalance": 0.0
  }
}
```

### Error Handling Strategy

1. **Catch at appropriate level**: Handle errors at the level where they can be meaningfully addressed
2. **Log with context**: Include session ID, message type, and relevant details
3. **Send appropriate response**: Use the correct error message format for the context
4. **Clean up resources**: Ensure connections and sessions are cleaned up on errors
5. **Don't crash**: Errors in one connection should not affect others

## Testing Strategy

### Unit Testing

Unit tests will verify individual components in isolation:

**Connection Manager Tests**
- Session creation and tracking
- Heartbeat monitoring
- Subscription management
- Cleanup on disconnect

**Message Router Tests**
- JSON parsing
- Schema validation
- Message routing to handlers
- Error handling

**Format Converter Tests**
- Codebuff to OpenAI conversion
- Response chunk creation
- Error message creation

**Action Handler Tests**
- Prompt processing
- Init handling
- Subscription management

### Property-Based Testing

Property-based tests will verify the correctness properties defined above using the Hypothesis library. Each property will be tested with randomly generated inputs to ensure it holds across all valid scenarios.

**Testing Framework**: Python's Hypothesis library
**Test Configuration**: Minimum 100 iterations per property test

**Property Test Structure**:
```python
from hypothesis import given, strategies as st

@given(
    session_id=st.text(min_size=1),
    messages=st.lists(st.dictionaries(...))
)
def test_property_X_description(session_id, messages):
    """
    Feature: codebuff-backend-compatibility, Property X: Description
    Validates: Requirements X.Y
    """
    # Test implementation
```

### Integration Testing

Integration tests will verify the system works end-to-end:

**WebSocket Connection Flow**
- Connect, identify, ping, disconnect
- Multiple concurrent connections
- Heartbeat timeout

**Prompt Flow**
- Send prompt action
- Receive streaming response chunks
- Receive final prompt-response
- Error handling

**Session Management**
- Initialize session with file context
- Use file context in prompts
- Session cleanup

### Testing Priorities

1. **Critical Path**: Connection management, prompt handling, streaming
2. **Error Handling**: All error scenarios
3. **Concurrency**: Multiple clients, session isolation
4. **Integration**: Backend factory, middleware, accounting

## Performance Considerations

### Scalability

**Target Metrics**:
- Support 100+ concurrent connections
- Handle 10+ requests per second per connection
- Maintain <100ms message routing latency
- Keep memory usage <100MB per 100 connections

**Optimization Strategies**:
- Use async/await for all I/O operations
- Implement connection pooling for backend requests
- Use efficient data structures for session tracking
- Implement session cleanup for inactive connections

### Resource Management

**Connection Limits**:
- Maximum 1000 concurrent connections
- Heartbeat timeout: 60 seconds
- Session cleanup: 1 hour of inactivity

**Memory Management**:
- Limit conversation history size per session
- Clean up completed requests
- Implement LRU cache for frequently accessed data

## Security Considerations

### Authentication (Future)

For MVP, authentication is minimal:
- Accept auth tokens but don't validate
- Track fingerprint IDs for attribution
- Return dummy usage values

Future iterations will add:
- Token validation against user database
- Rate limiting per user
- Usage tracking and billing

### Input Validation

All inputs must be validated:
- JSON schema validation for all messages
- Sanitize user-provided strings
- Validate model names against allowed list
- Limit message sizes

### Logging Security

Logs must not contain:
- Auth tokens
- Full message contents (only types and IDs)
- Sensitive file contents
- User credentials

## Deployment Considerations

### Configuration

New configuration options:
```yaml
codebuff:
  enabled: true
  websocket_path: "/ws"
  heartbeat_timeout_seconds: 60
  session_cleanup_hours: 1
  max_connections: 1000
  max_message_size_bytes: 1048576  # 1MB
```

### Monitoring

Key metrics to monitor:
- Active WebSocket connections
- Messages per second
- Average response time
- Error rate
- Session count
- Memory usage

### Logging

Log levels:
- DEBUG: Message routing, session operations
- INFO: Connections, disconnections, prompts
- WARNING: Validation failures, timeouts
- ERROR: Backend errors, unexpected failures

## Future Enhancements

### Phase 2: Tool & File Support

- Implement tool-call-request/response flow
- Implement read-files request/response flow
- Add tool execution tracking
- Add file access logging

### Phase 3: Advanced Features

- MCP tool support
- Real usage tracking and billing
- Session persistence across restarts
- Advanced authentication
- Rate limiting
- WebSocket compression
- Metrics and monitoring dashboard

## Dependencies

### New Dependencies

```toml
[tool.poetry.dependencies]
websockets = "^12.0"  # WebSocket server
pydantic = "^2.0"     # Already present, for message validation
```

### Existing Dependencies

The implementation will leverage:
- FastAPI for HTTP/WebSocket server
- Existing backend factory and connectors
- Existing response middleware
- Existing logging infrastructure
- Existing exception hierarchy
- Existing accounting utilities

## Implementation Notes

### MVP Scope

**In Scope**:
- WebSocket server on `/ws` endpoint
- Connection management with heartbeat
- Message parsing and validation
- Prompt action handling
- Streaming response chunks
- Init action handling
- Subscription management
- Basic error handling
- Logging

**Out of Scope** (for MVP):
- Tool call support
- File access support
- MCP tool support
- Real authentication
- Real usage tracking
- Session persistence
- Advanced error recovery

### Code Organization

```text
src/
  codebuff/
    __init__.py
    server.py              # WebSocket server
    connection_manager.py  # Connection and session management
    message_router.py      # Message routing
    handlers/
      __init__.py
      prompt_handler.py    # Prompt action handler
      init_handler.py      # Init action handler
      subscription_handler.py  # Subscription handler
    format_converter.py    # Format conversion
    schemas.py            # Pydantic models for messages
    exceptions.py         # Codebuff-specific exceptions

tests/
  unit/
    codebuff/
      test_connection_manager.py
      test_message_router.py
      test_format_converter.py
      handlers/
        test_prompt_handler.py
        test_init_handler.py
        test_subscription_handler.py
  property/
    codebuff/
      test_connection_properties.py
      test_message_properties.py
      test_streaming_properties.py
      test_session_properties.py
  integration/
    codebuff/
      test_websocket_flow.py
      test_prompt_flow.py
```

### Integration Points

**Startup Integration**:
```python
# In src/anthropic_server.py or main entry point
from src.codebuff.server import CodebuffWebSocketServer

# After creating FastAPI app
codebuff_server = CodebuffWebSocketServer(
    app=app,
    connection_manager=connection_manager,
    message_router=message_router,
    logger=logger
)
```

**Backend Integration**:
```python
# In PromptHandler
from src.core.backend_factory import BackendFactory

backend = backend_factory.get_backend(model=action.model)
response = await backend.stream_completion(messages)
```

**Middleware Integration**:
```python
# In PromptHandler
from src.response_middleware import apply_middleware

async for chunk in response:
    processed_chunk = await apply_middleware(chunk)
    await send_response_chunk(processed_chunk)
```
