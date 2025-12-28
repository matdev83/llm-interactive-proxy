# Implementation Plan

- [x] 1. Set up project structure and message schemas





  - Create `src/codebuff/` directory structure
  - Define Pydantic models for all Codebuff message types (identify, ping, subscribe, prompt, init, etc.)
  - Define Pydantic models for all server response types (ack, response-chunk, prompt-response, etc.)
  - Create custom exceptions for Codebuff-specific errors
  - _Requirements: 6.1, 6.3_

- [x] 1.1 Write property test for message schema validation


  - **Property 9: Schema validation**
  - **Validates: Requirements 6.3**


- [x] 2. Implement Connection Manager



  - Create `ConnectionManager` class with session tracking
  - Implement `connect()` method to register new connections
  - Implement `disconnect()` method to clean up sessions
  - Implement `get_session()` method to retrieve session data
  - Implement `update_last_seen()` method for heartbeat tracking
  - Implement subscription management methods (`subscribe()`, `unsubscribe()`, `get_subscribers()`)
  - Implement `cleanup_stale_connections()` method for timeout handling
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 9.1, 9.2, 9.4_

- [x] 2.1 Write property test for connection tracking

  - **Property 1: Connection tracking**
  - **Validates: Requirements 1.1**

- [x] 2.2 Write property test for session ID association

  - **Property 2: Session ID association**
  - **Validates: Requirements 1.2**

- [x] 2.3 Write property test for heartbeat updates

  - **Property 3: Heartbeat timestamp updates**
  - **Validates: Requirements 1.3**

- [x] 2.4 Write property test for session cleanup

  - **Property 4: Session cleanup on disconnect**
  - **Validates: Requirements 1.5**

- [x] 2.5 Write property test for subscription addition

  - **Property 27: Subscription addition**
  - **Validates: Requirements 9.1**

- [x] 2.6 Write property test for subscription removal

  - **Property 28: Subscription removal**
  - **Validates: Requirements 9.2**

- [x] 2.7 Write property test for subscription cleanup

  - **Property 30: Subscription cleanup**
  - **Validates: Requirements 9.4**

- [x] 2.8 Write unit tests for Connection Manager

  - Test session creation and retrieval
  - Test heartbeat monitoring
  - Test subscription management
  - Test cleanup on disconnect
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 9.1, 9.2, 9.4_
-

- [x] 3. Implement Format Converter




  - Create `FormatConverter` class
  - Implement `codebuff_to_openai()` method to convert message formats
  - Implement `create_response_chunk()` method for streaming responses
  - Implement `create_prompt_response()` method for final responses
  - Implement `create_error_response()` method for error messages
  - Implement `create_init_response()` method for init responses
  - _Requirements: 2.2, 3.1, 3.2_

- [x] 3.1 Write property test for format conversion validity


  - **Property 6: Format conversion validity**
  - **Validates: Requirements 2.2**

- [x] 3.2 Write property test for chunk conversion


  - **Property 11: Chunk conversion**
  - **Validates: Requirements 3.1**

- [x] 3.3 Write property test for user input ID correlation


  - **Property 12: User input ID correlation**
  - **Validates: Requirements 3.2**

- [x] 3.4 Write unit tests for Format Converter


  - Test Codebuff to OpenAI conversion
  - Test response chunk creation
  - Test error message creation
  - _Requirements: 2.2, 3.1, 3.2_
-

- [x] 4. Implement Message Router




  - Create `MessageRouter` class
  - Implement `route_message()` method to parse and route messages
  - Implement `validate_message()` method for schema validation
  - Implement routing logic for identify, ping, subscribe, unsubscribe, and action messages
  - Implement error handling for invalid messages
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 4.1 Write property test for JSON parsing


  - **Property 8: JSON parsing**
  - **Validates: Requirements 6.1**

- [x] 4.2 Write property test for valid message acknowledgment


  - **Property 10: Valid message acknowledgment**
  - **Validates: Requirements 6.5**

- [x] 4.3 Write unit tests for Message Router


  - Test JSON parsing
  - Test schema validation
  - Test message routing
  - Test error handling
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
-

- [x] 5. Implement Prompt Handler



  - Create `PromptHandler` class
  - Implement `handle_prompt()` method to process LLM requests
  - Integrate with existing backend factory to select appropriate backend
  - Implement streaming response handling
  - Convert backend responses to response-chunk actions
  - Send final prompt-response action on completion
  - Implement error handling for backend failures
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 5.1 Write property test for message extraction


  - **Property 5: Message extraction**
  - **Validates: Requirements 2.1**

- [x] 5.2 Write property test for backend routing

  - **Property 7: Backend routing**
  - **Validates: Requirements 2.3**

- [x] 5.3 Write property test for cancellation cleanup

  - **Property 13: Cancellation cleanup**
  - **Validates: Requirements 3.5**

- [x] 5.4 Write property test for backend factory usage

  - **Property 31: Backend factory usage**
  - **Validates: Requirements 10.1**

- [x] 5.5 Write property test for middleware application

  - **Property 32: Middleware application**
  - **Validates: Requirements 10.2**

- [x] 5.6 Write unit tests for Prompt Handler


  - Test prompt processing
  - Test streaming response handling
  - Test error handling
  - Test cancellation
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 6. Implement Init Handler





  - Create `InitHandler` class
  - Implement `handle_init()` method to initialize sessions
  - Store file context in session state
  - Return init-response with dummy usage values
  - Implement error handling for initialization failures
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 6.1 Write property test for file context storage


  - **Property 17: File context storage**
  - **Validates: Requirements 5.1**

- [x] 6.2 Write property test for file context persistence


  - **Property 18: File context persistence**
  - **Validates: Requirements 5.3**

- [x] 6.3 Write unit tests for Init Handler


  - Test session initialization
  - Test file context storage
  - Test error handling
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 7. Implement Subscription Handler





  - Create `SubscriptionHandler` class
  - Implement `handle_subscribe()` method
  - Implement `handle_unsubscribe()` method
  - Integrate with Connection Manager for subscription tracking
  - _Requirements: 9.1, 9.2, 9.5_

- [x] 7.1 Write property test for topic message distribution


  - **Property 29: Topic message distribution**
  - **Validates: Requirements 9.3**

- [x] 7.2 Write unit tests for Subscription Handler


  - Test subscribe handling
  - Test unsubscribe handling
  - Test error handling
  - _Requirements: 9.1, 9.2, 9.5_

- [x] 8. Implement WebSocket Server




  - Create `CodebuffWebSocketServer` class
  - Implement `handle_connection()` method for WebSocket lifecycle
  - Implement `send_message()` method to send messages to clients
  - Integrate with Connection Manager for session tracking
  - Integrate with Message Router for message processing
  - Implement heartbeat monitoring background task
  - Implement graceful shutdown handling
  - _Requirements: 1.1, 1.4, 1.5_

- [x] 8.1 Write property test for session isolation

  - **Property 19: Session isolation**
  - **Validates: Requirements 7.1**

- [x] 8.2 Write property test for operation isolation

  - **Property 20: Operation isolation**
  - **Validates: Requirements 7.2**

- [x] 8.3 Write property test for disconnect isolation

  - **Property 21: Disconnect isolation**
  - **Validates: Requirements 7.3**

- [x] 8.4 Write unit tests for WebSocket Server

  - Test connection handling
  - Test message sending
  - Test heartbeat monitoring
  - Test graceful shutdown
  - _Requirements: 1.1, 1.4, 1.5_

- [x] 9. Implement authentication and usage tracking




  - Implement auth token validation (accept but don't validate for MVP)
  - Implement fingerprint ID tracking
  - Implement cost attribution to fingerprint/session
  - Integrate with existing accounting utilities
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 9.1 Write property test for token validation


  - **Property 14: Token validation**
  - **Validates: Requirements 4.1**

- [x] 9.2 Write property test for fingerprint association


  - **Property 15: Fingerprint association**
  - **Validates: Requirements 4.4**

- [x] 9.3 Write property test for cost attribution


  - **Property 16: Cost attribution**
  - **Validates: Requirements 4.5**

- [x] 9.4 Write property test for accounting integration


  - **Property 33: Accounting integration**
  - **Validates: Requirements 10.3**

- [x] 9.5 Write unit tests for authentication and usage tracking


  - Test auth token handling
  - Test fingerprint tracking
  - Test cost attribution
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_
-

- [x] 10. Implement logging



  - Add connection logging with session IDs
  - Add message logging with types and session IDs
  - Add error logging with full context
  - Add disconnection logging
  - Ensure sensitive data is not logged
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [x] 10.1 Write property test for connection logging


  - **Property 22: Connection logging**
  - **Validates: Requirements 8.1**

- [x] 10.2 Write property test for message logging


  - **Property 23: Message logging**
  - **Validates: Requirements 8.2**

- [x] 10.3 Write property test for error logging


  - **Property 24: Error logging**
  - **Validates: Requirements 8.3**

- [x] 10.4 Write property test for disconnect logging


  - **Property 25: Disconnect logging**
  - **Validates: Requirements 8.4**

- [x] 10.5 Write property test for sensitive data exclusion


  - **Property 26: Sensitive data exclusion**
  - **Validates: Requirements 8.5**

- [x] 10.6 Write unit tests for logging


  - Test connection logging
  - Test message logging
  - Test error logging
  - Test sensitive data filtering
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [x] 11. Implement exception handling





  - Create Codebuff-specific exception classes
  - Ensure all exceptions inherit from existing exception hierarchy
  - Implement error response formatting
  - Add error handling in all components
  - _Requirements: 10.4_

- [x] 11.1 Write property test for exception hierarchy usage


  - **Property 34: Exception hierarchy usage**
  - **Validates: Requirements 10.4**

- [x] 11.2 Write unit tests for exception handling


  - Test exception creation
  - Test error response formatting
  - Test error propagation
  - _Requirements: 10.4_
-

- [x] 12. Integrate with existing server infrastructure




  - Add WebSocket endpoint to FastAPI app
  - Register Codebuff server on startup
  - Add configuration options for Codebuff
  - Update server startup sequence
  - _Requirements: 10.5_

- [x] 12.1 Write integration test for server startup


  - Test WebSocket endpoint registration
  - Test configuration loading
  - _Requirements: 10.5_
- [x] 13. Write integration tests



- [ ] 13. Write integration tests

  - Test complete WebSocket connection flow (connect, identify, ping, disconnect)
  - Test complete prompt flow (send prompt, receive chunks, receive final response)
  - Test session initialization flow
  - Test subscription flow
  - Test error scenarios (invalid messages, backend errors, timeouts)
  - Test concurrent connections
  - _Requirements: All_

- [x] 14. Add configuration and documentation







  - Add Codebuff configuration section to config schema
  - Update README with Codebuff backend setup instructions
  - Add example configuration file
  - Document message formats and protocol
  - _Requirements: All_
- [x] 15. Final checkpoint - Ensure all tests pass



- [ ] 15. Final checkpoint - Ensure all tests pass

  - Ensure all tests pass, ask the user if questions arise.
