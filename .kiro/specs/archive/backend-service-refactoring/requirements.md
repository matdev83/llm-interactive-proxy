# Requirements Document

## Introduction

This document specifies the requirements for refactoring the `BackendService` class (`src/core/services/backend_service.py`) which has grown into a "God Object" anti-pattern. The current implementation violates multiple SOLID principles, contains mixed responsibilities, and is difficult to test and maintain. The refactoring aims to decompose this monolithic class into smaller, focused services while preserving all existing public APIs and ensuring zero regressions in the test suite.

## Glossary

- **BackendService**: The current monolithic service class responsible for LLM backend interactions, failover, rate limiting, usage tracking, wire capture, and request/response transformation.
- **God Object**: An anti-pattern where a single class knows too much or does too much, violating the Single Responsibility Principle.
- **SRP (Single Responsibility Principle)**: A class should have only one reason to change.
- **OCP (Open/Closed Principle)**: Software entities should be open for extension but closed for modification.
- **LSP (Liskov Substitution Principle)**: Objects of a superclass should be replaceable with objects of subclasses without affecting correctness.
- **ISP (Interface Segregation Principle)**: Clients should not be forced to depend on interfaces they do not use.
- **DIP (Dependency Inversion Principle)**: High-level modules should not depend on low-level modules; both should depend on abstractions.
- **DI Container**: Dependency Injection container used for managing service lifecycles and dependencies.
- **Wire Capture**: The mechanism for capturing request/response traffic for debugging and replay.
- **Failover**: The process of switching to an alternative backend when the primary fails.
- **SSE (Server-Sent Events)**: A protocol for streaming responses from server to client.

## Requirements

### Requirement 1

**User Story:** As a developer, I want the backend service to follow the Single Responsibility Principle, so that each component has one clear purpose and is easier to understand and maintain.

#### Acceptance Criteria

1. WHEN the BackendService is refactored THEN the system SHALL separate stream formatting logic into a dedicated StreamFormattingService
2. WHEN the BackendService is refactored THEN the system SHALL separate usage tracking wrapper logic into a dedicated UsageTrackingWrapper service
3. WHEN the BackendService is refactored THEN the system SHALL separate model alias resolution into a dedicated ModelAliasResolver service
4. WHEN the BackendService is refactored THEN the system SHALL separate URI parameter application into a dedicated URIParameterApplicator service
5. WHEN the BackendService is refactored THEN the system SHALL separate reasoning configuration application into a dedicated ReasoningConfigApplicator service
6. WHEN the BackendService is refactored THEN the system SHALL separate planning phase management into a dedicated PlanningPhaseManager service
7. WHEN the BackendService is refactored THEN the system SHALL separate backend lifecycle management into a dedicated BackendLifecycleManager service

### Requirement 2

**User Story:** As a developer, I want the refactored services to use proper dependency injection, so that components are loosely coupled and easily testable.

#### Acceptance Criteria

1. WHEN new services are created THEN the system SHALL define interfaces for each new service in the interfaces directory
2. WHEN new services are created THEN the system SHALL register all new services in the DI container
3. WHEN the BackendService is refactored THEN the system SHALL inject all dependencies through the constructor
4. WHEN the BackendService is refactored THEN the system SHALL remove all inline imports and service instantiation from method bodies
5. WHEN services depend on other services THEN the system SHALL depend on interfaces rather than concrete implementations

### Requirement 3

**User Story:** As a developer, I want the public API of BackendService to remain unchanged, so that existing code continues to work without modification.

#### Acceptance Criteria

1. WHEN the refactoring is complete THEN the IBackendService interface SHALL remain unchanged
2. WHEN the refactoring is complete THEN the call_completion method signature SHALL remain unchanged
3. WHEN the refactoring is complete THEN the chat_completions method signature SHALL remain unchanged
4. WHEN the refactoring is complete THEN the validate_backend_and_model method signature SHALL remain unchanged
5. WHEN the refactoring is complete THEN the get_backend method signature SHALL remain unchanged
6. WHEN the refactoring is complete THEN the get_active_backends method signature SHALL remain unchanged

### Requirement 4

**User Story:** As a developer, I want the refactored code to maintain full test coverage, so that I can be confident the refactoring introduces no regressions.

#### Acceptance Criteria

1. WHEN the refactoring is complete THEN the system SHALL pass all existing unit tests without modification
2. WHEN the refactoring is complete THEN the system SHALL pass all existing integration tests without modification
3. WHEN new services are created THEN the system SHALL include unit tests for each new service
4. WHEN the refactoring is complete THEN the test suite SHALL achieve zero test failures
5. WHEN responsibilities are extracted THEN BackendService SHALL retain existing helper/private methods with compatible signatures (e.g., `_stream_as_sse_bytes`, `_wrap_stream_for_usage`, `_apply_model_aliases`, `_apply_reasoning_config`, `_apply_uri_parameters`, planning phase helpers, lifecycle helpers, `_normalize_provider_exception`) as thin delegating wrappers so existing tests and scripts do not require changes
6. WHEN helpers are delegated to extracted services THEN those services SHALL preserve the observable invariants documented in Design → “Invariants and Gotchas to Preserve”

### Requirement 5

**User Story:** As a developer, I want the stream formatting logic to be isolated, so that SSE encoding and chunk validation can be tested and modified independently.

#### Acceptance Criteria

1. WHEN a StreamFormattingService is created THEN the system SHALL provide a method to convert domain chunks to SSE-encoded bytes
2. WHEN a StreamFormattingService is created THEN the system SHALL provide a method to validate completion tokens
3. WHEN a StreamFormattingService is created THEN the system SHALL handle ProcessedResponse, dict, str, and bytes chunk types
4. WHEN a StreamFormattingService is created THEN the system SHALL properly detect and emit [DONE] markers

### Requirement 6

**User Story:** As a developer, I want the usage tracking wrapper to be isolated, so that metrics collection can be modified without affecting core backend logic.

#### Acceptance Criteria

1. WHEN a UsageTrackingWrapper is created THEN the system SHALL wrap streams to track first token time
2. WHEN a UsageTrackingWrapper is created THEN the system SHALL accumulate usage data from stream chunks
3. WHEN a UsageTrackingWrapper is created THEN the system SHALL record response metrics on stream completion
4. WHEN a UsageTrackingWrapper is created THEN the system SHALL calculate stream tokens per second

### Requirement 7

**User Story:** As a developer, I want the model alias resolution to be isolated, so that model name transformations can be configured and tested independently.

#### Acceptance Criteria

1. WHEN a ModelAliasResolver is created THEN the system SHALL apply regex-based model name transformations
2. WHEN a ModelAliasResolver is created THEN the system SHALL support capture group expansion in replacements
3. WHEN a ModelAliasResolver is created THEN the system SHALL handle invalid regex patterns gracefully
4. WHEN a ModelAliasResolver is created THEN the system SHALL return the original model name when no aliases match

### Requirement 8

**User Story:** As a developer, I want the URI parameter application to be isolated, so that parameter precedence rules can be tested and modified independently.

#### Acceptance Criteria

1. WHEN a URIParameterApplicator is created THEN the system SHALL resolve parameters from URI, headers, config, and session sources
2. WHEN a URIParameterApplicator is created THEN the system SHALL apply correct precedence (session > URI > headers > config)
3. WHEN a URIParameterApplicator is created THEN the system SHALL coerce parameter values to correct types
4. WHEN a URIParameterApplicator is created THEN the system SHALL handle edit-precision mode overrides

### Requirement 9

**User Story:** As a developer, I want the reasoning configuration application to be isolated, so that reasoning model parameters can be managed independently.

#### Acceptance Criteria

1. WHEN a ReasoningConfigApplicator is created THEN the system SHALL apply temperature, top_p, and top_k from session config
2. WHEN a ReasoningConfigApplicator is created THEN the system SHALL apply reasoning_effort and thinking_budget parameters
3. WHEN a ReasoningConfigApplicator is created THEN the system SHALL apply user prompt prefix and suffix modifications
4. WHEN a ReasoningConfigApplicator is created THEN the system SHALL respect edit-precision mode constraints

### Requirement 10

**User Story:** As a developer, I want the planning phase management to be isolated, so that multi-turn planning logic can be tested and modified independently.

#### Acceptance Criteria

1. WHEN a PlanningPhaseManager is created THEN the system SHALL apply planning phase model overrides when conditions are met
2. WHEN a PlanningPhaseManager is created THEN the system SHALL track turn counts and file write counts
3. WHEN a PlanningPhaseManager is created THEN the system SHALL restore original routes when planning phase completes
4. WHEN a PlanningPhaseManager is created THEN the system SHALL count file write tool calls in responses

### Requirement 11

**User Story:** As a developer, I want the backend lifecycle management to be isolated, so that backend creation, caching, and shutdown can be managed independently.

#### Acceptance Criteria

1. WHEN a BackendLifecycleManager is created THEN the system SHALL manage per-session backend caching with LRU eviction
2. WHEN a BackendLifecycleManager is created THEN the system SHALL handle backend shutdown with proper async cleanup
3. WHEN a BackendLifecycleManager is created THEN the system SHALL track permanently disabled backends
4. WHEN a BackendLifecycleManager is created THEN the system SHALL support backend recovery attempts

### Requirement 12

**User Story:** As a developer, I want the exception normalization to be isolated, so that provider-specific errors can be translated consistently.

#### Acceptance Criteria

1. WHEN an ExceptionNormalizer is created THEN the system SHALL translate HTTPException 429 to RateLimitExceededError
2. WHEN an ExceptionNormalizer is created THEN the system SHALL translate HTTPException 4xx to InvalidRequestError
3. WHEN an ExceptionNormalizer is created THEN the system SHALL translate HTTPException 5xx to BackendError
4. WHEN an ExceptionNormalizer is created THEN the system SHALL preserve retry-after headers in rate limit errors

### Requirement 13

**User Story:** As a developer, I want the refactored code to follow consistent coding standards, so that the codebase remains maintainable.

#### Acceptance Criteria

1. WHEN new services are created THEN the system SHALL pass ruff linting checks
2. WHEN new services are created THEN the system SHALL pass black formatting checks
3. WHEN new services are created THEN the system SHALL pass mypy type checking
4. WHEN new services are created THEN the system SHALL include docstrings for all public methods
