# Implementation Plan

- [x] 1. Define connector subcomponent contracts and shared data boundaries
- [x] 1.1 Define service boundaries for credential coordination, model discovery, health checks, chat completion coordination, error mapping, VTC wrapping, and streaming orchestration
  - Specify inputs, outputs, and async behavior to support DI and test seams
  - Isolate optional features so they can be enabled or disabled without impacting core flow
  - _Requirements: 1.1, 1.2, 1.4, 3.1, 3.3, 4.2_
  - **Verified**: All interfaces match design.md specifications with complete documentation (preconditions, postconditions, invariants, data flow)

- [x] 1.2 Introduce a typed credential payload shared across services without changing credential loading semantics
  - Preserve existing fields and allow forward-compatible provider attributes
  - Keep validation boundaries explicit for unit testing
  - _Requirements: 1.1, 1.3, 4.1, 8.3_
  - **Verified**: Shared data models (`GeminiOAuthCredentials`, `PreparedChatRequest`, `StreamWrapper`, `ITokenRefresher`) properly typed and documented with data flow contracts
  - **Verified**: All unit tests pass (89 tests) validating contract compliance

- [x] 2. Implement credential lifecycle and model registry services
- [x] 2.1 Build the credential coordination service for load, refresh, validation, and watcher state management
  - Maintain existing error categories and propagation behavior
  - Keep token refresh and watcher behavior consistent with current runtime
  - _Requirements: 1.1, 1.2, 1.3, 2.4, 4.1, 4.2, 6.1, 8.3_

- [x] 2.2 (P) Build the model registry service for discovery, caching, and name mapping
  - Preserve public model list and alias mapping behavior
  - Keep cached lookups to avoid new latency or throughput regressions
  - _Requirements: 1.1, 2.1, 2.2, 4.1, 5.1, 5.3_

- [x] 3. Implement health check and error mapping services
- [x] 3.1 Build the health check service to enforce first-use readiness without adding new endpoints
  - Use existing endpoints and preserve health semantics and error propagation
  - _Requirements: 1.1, 2.4, 6.1, 7.3_

- [x] 3.2 (P) Build the error mapping service to normalize connector exceptions
  - Preserve status codes, error categories, and rate-limit semantics
  - _Requirements: 1.2, 2.4, 3.3, 4.1, 6.1, 6.2, 6.3_

- [x] 4. Implement chat completion orchestration and optional streaming wrappers
- [x] 4.1 (P) Build optional VTC wrapper assembly for tool-call streaming features
  - Resolve optional tool services via DI with safe fallback when unavailable
  - Preserve streaming ordering and tool-call data integrity
  - _Requirements: 1.4, 2.3, 3.2, 3.4, 4.1_

- [x] 4.2 Build the chat completion coordinator to orchestrate request preparation, streaming execution, and response accumulation
  - Ensure response envelopes and chunk order remain identical to current behavior
  - Avoid additional work in the streaming hot path to protect first-byte latency
  - _Requirements: 1.2, 2.2, 2.3, 4.1, 4.3, 5.2_

- [x] 4.3 Integrate the existing streaming orchestrator as the default execution path
  - Preserve prefetch and post-processing order for streaming and non-streaming flows
  - _Requirements: 2.2, 2.3, 4.3_

- [x] 5. Refactor connector facade and DI wiring
- [x] 5.1 Refactor the connector facade to be orchestration-only while preserving public methods and backend registration
  - Keep backend type and import-time registration unchanged
  - Ensure behavior remains stable for configuration, error categories, and response schemas
  - _Requirements: 1.5, 2.1, 2.2, 2.5, 4.4_
  - **Verified**: Connector delegates to coordinators (lines 989, 1592, 1811), public methods preserved, backend registration unchanged

- [x] 5.2 Wire services through DI with a service-provider fallback for optional dependencies
  - Register coordinator services with appropriate lifetimes and reuse shared utilities
  - Keep test doubles injectable without modifying production code
  - _Requirements: 3.2, 3.3, 3.4, 4.2_
  - **Verified**: DI registration in `src/core/di/registrations/_backend/gemini.py`, connector uses `get_service_provider()` with fallback (lines 427-496)

- [x] 5.3 Validate observability and security invariants across the refactor
  - Preserve wire capture payloads, logging structure, and redaction of secrets
  - _Requirements: 2.4, 7.1, 7.2, 8.1, 8.2_
  - **Verified**: Wire capture paths unchanged (coordinator → orchestrator → same envelope types), logging structure preserved (same logger instances), credential access patterns unchanged

- [x] 6. Testing and regression validation
- [x] 6.1 Write unit tests for credential, model, health, error mapping, and VTC wrapper behaviors
  - Cover success and failure paths with mocked dependencies
  - _Requirements: 4.1, 4.2, 4.3_
  - **Verified**: 133 unit tests covering all components with success/failure paths:
    - `test_credential_coordinator.py` (13 tests)
    - `test_credential_coordinator_failures.py` (16 tests) - Added test for file watcher state consistency
    - `test_model_registry.py` (16 tests)
    - `test_health_check_service.py` (13 tests)
    - `test_health_check_service_failures.py` (14 tests)
    - `test_error_mapper.py` (10 tests)
    - `test_vtc_wrapper_builder.py` (14 tests) - Added tests for individual service resolution failures (ToolCallReactorService, IToolArgumentsParser, IToolArgumentsFixupPipeline, all services missing)
    - `test_chat_completion_coordinator.py` (16 tests) - Added tests for HTTPException handling and exc_info logging verification
    - `test_interfaces.py` (8 tests)
    - `test_models.py` (13 tests)

- [x] 6.2 Write integration tests for connector wiring, streaming and non-streaming flows, and backend registration continuity
  - Validate response envelopes, chunk ordering, and configuration compatibility
  - _Requirements: 2.1, 2.2, 2.3, 2.5, 3.2, 5.1, 5.2, 5.3_
  - **Verified**: 39 integration tests in `test_gemini_base_wiring_integration.py` covering:
    - Connector wiring (interface implementation checks)
    - Streaming and non-streaming response envelope structure
    - Backend registration continuity
    - Configuration compatibility
    - Service resolution fallback behavior
    - Chunk ordering preservation
    - Error mapper integration through connector facade (with/without mapper)
    - Model registry API discovery failure and fallback behavior
    - Connector state synchronization (credential and model state sync)

- [x] 6.3 Add regression checks for observability, reliability, and credential handling invariants
  - Validate error propagation, rate-limit handling, health check behavior, and capture/log redaction
  - _Requirements: 6.1, 6.2, 6.3, 7.1, 7.2, 7.3, 8.1, 8.2, 8.3_
  - **Verified**: 36 regression tests in `test_gemini_base_regression.py` covering:
    - Error propagation invariants (status codes, backend names, exception chaining)
    - Rate-limit handling (429 status preservation)
    - Health check behavior (existing endpoints only, failure handling)
    - Health check endpoint validation (correct URLs, fallback order, no new endpoints)
    - Credential loading mechanisms (CredentialLoader, TokenManager, FileWatcher)
    - Logging structure (exc_info patterns, runtime verification)
    - Capture payload compatibility (ResponseEnvelope structure, wire capture payload structure validation)
    - Auth retry semantics (timeout constant, retry flag)
    - Validation behavior (InvalidRequestError preservation)
    - Circuit breaker compatibility (required error fields)
    - Wire capture payload structure (ResponseEnvelope and StreamingResponseEnvelope field requirements)
    - exc_info runtime verification (actual logger calls with exc_info=True)
  - **Verified**: Performance regression tests in `test_gemini_base_performance_regression.py` covering:
    - Response latency regression (Requirement 5.1) - Coordinator overhead verification
    - Streaming first-byte regression (Requirement 5.2) - First chunk latency verification
    - Throughput maintenance (Requirement 5.3) - Concurrent request handling verification
