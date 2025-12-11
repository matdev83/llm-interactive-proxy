# Requirements Document

## Introduction

This document specifies the requirements for implementing Codebuff backend compatibility in the LLM proxy server. Codebuff is a coding agent that uses a WebSocket-based protocol to communicate with its backend. This feature will enable the proxy to act as a drop-in replacement for the Codebuff backend, allowing Codebuff clients to route their LLM requests through this proxy infrastructure.

## Glossary

- **Codebuff**: A coding agent platform that uses AI models to assist with software development
- **WebSocket**: A protocol providing full-duplex communication channels over a single TCP connection
- **Client Action**: A message sent from the Codebuff client to the server
- **Server Action**: A message sent from the server to the Codebuff client
- **Prompt Action**: A client action containing an LLM request with conversation history and parameters
- **Response Chunk**: A server action containing a portion of streaming LLM response text
- **Session State**: The conversation history and context maintained for a client connection
- **Tool Call**: A request for the client to execute a local tool (file operations, shell commands, etc.)
- **Fingerprint ID**: A unique identifier for a Codebuff client instance
- **Auth Token**: An authentication credential provided by the client
- **Switchboard**: A message routing system that manages WebSocket connections and topics

## Requirements

### Requirement 1

**User Story:** As a Codebuff user, I want to connect my Codebuff client to this proxy server, so that I can route my LLM requests through the proxy's backend infrastructure.

#### Acceptance Criteria

1. WHEN a Codebuff client connects to the `/ws` endpoint THEN the system SHALL establish a WebSocket connection and track the client session
2. WHEN the client sends an `identify` message THEN the system SHALL store the client session ID and associate it with the WebSocket connection
3. WHEN the client sends a `ping` message THEN the system SHALL update the last-seen timestamp for that connection
4. WHEN a connection has not sent a ping for 60 seconds THEN the system SHALL terminate that connection
5. WHEN a client disconnects THEN the system SHALL clean up the session state and remove the connection from tracking

### Requirement 2

**User Story:** As a Codebuff user, I want to send prompts to the LLM through the proxy, so that I can get AI-powered coding assistance.

#### Acceptance Criteria

1. WHEN a client sends a `prompt` action THEN the system SHALL extract the conversation messages and model selection
2. WHEN processing a prompt action THEN the system SHALL convert the Codebuff message format to OpenAI-compatible format
3. WHEN the prompt is converted THEN the system SHALL route the request to the appropriate backend based on the model specified
4. WHEN the backend is not available THEN the system SHALL send a `prompt-error` action to the client with an error message
5. WHEN the model is not supported THEN the system SHALL send a `prompt-error` action indicating the unsupported model

### Requirement 3

**User Story:** As a Codebuff user, I want to receive streaming responses from the LLM, so that I can see the AI's output as it is generated.

#### Acceptance Criteria

1. WHEN the backend starts streaming a response THEN the system SHALL send `response-chunk` actions to the client for each text chunk
2. WHEN a response chunk is sent THEN the system SHALL include the user input ID to correlate with the original request
3. WHEN the stream completes successfully THEN the system SHALL send a `prompt-response` action with the final session state
4. WHEN the stream encounters an error THEN the system SHALL send a `prompt-error` action with the error details
5. WHEN the client cancels a request THEN the system SHALL stop streaming and clean up the request state

### Requirement 4

**User Story:** As a Codebuff user, I want the system to handle authentication, so that only authorized clients can use the proxy.

#### Acceptance Criteria

1. WHEN a client sends a `prompt` or `init` action THEN the system SHALL validate the auth token if provided
2. WHEN an auth token is invalid THEN the system SHALL send an `action-error` with an authentication failure message
3. WHEN no auth token is provided THEN the system SHALL allow the request to proceed (for MVP)
4. WHEN a fingerprint ID is provided THEN the system SHALL associate it with the client session
5. WHEN tracking usage THEN the system SHALL attribute costs to the fingerprint ID or session

### Requirement 5

**User Story:** As a Codebuff user, I want to initialize a session with project context, so that the AI understands my codebase.

#### Acceptance Criteria

1. WHEN a client sends an `init` action THEN the system SHALL store the file context for that session
2. WHEN an init action is processed THEN the system SHALL send an `init-response` with usage information
3. WHEN file context is provided THEN the system SHALL make it available for subsequent prompt actions
4. WHEN a session is initialized THEN the system SHALL return dummy usage values (0 credits used, unlimited balance)
5. WHEN initialization fails THEN the system SHALL send an `action-error` with the failure reason

### Requirement 6

**User Story:** As a developer, I want the system to validate all incoming messages, so that malformed messages are rejected early.

#### Acceptance Criteria

1. WHEN a message is received THEN the system SHALL parse it as JSON
2. WHEN JSON parsing fails THEN the system SHALL send an `ack` message with success=false and an error message
3. WHEN a parsed message is received THEN the system SHALL validate it against the expected schema
4. WHEN schema validation fails THEN the system SHALL send an `ack` message with success=false and validation errors
5. WHEN a message is valid THEN the system SHALL send an `ack` message with success=true

### Requirement 7

**User Story:** As a developer, I want the system to handle multiple concurrent client connections, so that multiple users can use the proxy simultaneously.

#### Acceptance Criteria

1. WHEN multiple clients connect THEN the system SHALL maintain separate session state for each client
2. WHEN one client sends a request THEN the system SHALL not affect other clients' sessions
3. WHEN a client disconnects THEN the system SHALL not affect other active connections
4. WHEN the system is under load THEN the system SHALL handle at least 100 concurrent connections
5. WHEN memory usage grows THEN the system SHALL clean up inactive sessions after 1 hour of inactivity

### Requirement 8

**User Story:** As a developer, I want comprehensive logging of WebSocket communication, so that I can debug issues and monitor system behavior.

#### Acceptance Criteria

1. WHEN a client connects THEN the system SHALL log the connection event with session ID
2. WHEN a message is received THEN the system SHALL log the message type and session ID
3. WHEN an error occurs THEN the system SHALL log the error with full context including session ID and message details
4. WHEN a client disconnects THEN the system SHALL log the disconnection event
5. WHEN logging THEN the system SHALL not log sensitive information like auth tokens or full message contents

### Requirement 9

**User Story:** As a Codebuff user, I want the system to handle subscription-based message routing, so that I can receive targeted updates.

#### Acceptance Criteria

1. WHEN a client sends a `subscribe` action THEN the system SHALL add the client to the specified topics
2. WHEN a client sends an `unsubscribe` action THEN the system SHALL remove the client from the specified topics
3. WHEN a message is published to a topic THEN the system SHALL send it to all subscribed clients
4. WHEN a client disconnects THEN the system SHALL remove all subscriptions for that client
5. WHEN subscribing to an invalid topic THEN the system SHALL send an `ack` with success=false

### Requirement 10

**User Story:** As a developer, I want the system to integrate with the existing proxy infrastructure, so that I can leverage existing backend connectors and middleware.

#### Acceptance Criteria

1. WHEN routing an LLM request THEN the system SHALL use the existing backend factory to select the appropriate connector
2. WHEN processing a response THEN the system SHALL apply existing response middleware
3. WHEN tracking usage THEN the system SHALL use the existing accounting utilities
4. WHEN handling errors THEN the system SHALL use the existing exception hierarchy
5. WHEN the system starts THEN the system SHALL register the WebSocket endpoint alongside existing HTTP endpoints
