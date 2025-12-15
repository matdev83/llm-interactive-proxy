# Requirements Document

## Introduction

This document specifies the requirements for refactoring the `BackendService` class (`src/core/services/backend_service.py`) which has grown into a "God Object" anti-pattern. The current implementation is approximately 2109 lines long and violates multiple SOLID principles, contains mixed responsibilities, and is difficult to test and maintain. The refactoring aims to decompose this monolithic class into smaller, focused services while preserving all existing public APIs and ensuring zero regressions in the test suite.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers integrating LLM capabilities via unified API
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications

## Glossary

- **BackendService**: The current monolithic service class responsible for LLM backend interactions, failover, rate limiting, usage tracking, wire capture, and request/response transformation.
- **God Object**: An anti-pattern where a single class knows too much or does too much, violating the Single Responsibility Principle.
- **SRP (Single Responsibility Principle)**: A class should have only one reason to change.
- **OCP (Open/Closed Principle)**: Software entities should be open for extension but closed for modification.
- **LSP (Liskov Substitution Principle)**: Objects of a superclass should be replaceable with objects of subclasses without affecting correctness.
- **ISP (Interface Segregation Principle)**: Clients should not be forced to depend on interfaces they do not use.
- **DIP (Dependency Inversion Principle)**: High-level modules should not depend on low-level modules; both should depend on abstractions.
- **DI Container**: Dependency Injection container (`ServiceCollection`) used for managing service lifecycles and dependencies.
- **Wire Capture**: The mechanism for capturing request/response traffic for debugging and replay (CBOR-encoded).
- **Failover**: The process of switching to an alternative backend when the primary fails.
- **SSE (Server-Sent Events)**: A protocol for streaming responses from server to client.

## Requirements

### Requirement 1: Single Responsibility Principle Compliance

**Objective:** As a developer, I want the BackendService to follow the Single Responsibility Principle, so that each component has one clear purpose and is easier to understand, test, and maintain.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. WHEN the BackendService is refactored THEN the system SHALL separate backend lifecycle management (creation, caching, per-session limits) into a dedicated BackendLifecycleManager service
2. WHEN the BackendService is refactored THEN the system SHALL separate failover coordination logic into a dedicated FailoverCoordinator service
3. WHEN the BackendService is refactored THEN the system SHALL separate backend and model resolution logic into a dedicated BackendModelResolver service
4. WHEN the BackendService is refactored THEN the system SHALL separate request transformation logic (model aliases, reasoning config, URI parameters) into a dedicated RequestTransformer service
5. WHEN the BackendService is refactored THEN the system SHALL separate exception normalization logic into a dedicated ExceptionNormalizer service
6. WHEN the BackendService is refactored THEN the system SHALL separate stream processing logic (SSE encoding, chunk validation, session ID resolution) into a dedicated StreamProcessor service
7. WHEN the BackendService is refactored THEN the system SHALL separate failure handling strategy execution into a dedicated FailureStrategyExecutor service
8. WHEN the BackendService is refactored THEN the system SHALL reduce BackendService to orchestration responsibilities only (coordinating the extracted services)

#### Technical Constraints

- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### Requirement 2: Dependency Injection and Loose Coupling

**Objective:** As a developer, I want the refactored services to use proper dependency injection, so that components are loosely coupled and easily testable.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. WHEN new services are created THEN the system SHALL define interfaces for each new service in the `src/core/interfaces/` directory following the `I*` naming convention
2. WHEN new services are created THEN the system SHALL register all new services in the DI container (`ServiceCollection` in `src/core/di/container.py`)
3. WHEN the BackendService is refactored THEN the system SHALL inject all dependencies through the constructor (no optional parameters with inline instantiation)
4. WHEN the BackendService is refactored THEN the system SHALL remove all inline imports and service instantiation from method bodies
5. WHEN services depend on other services THEN the system SHALL depend on interfaces rather than concrete implementations
6. WHEN the BackendService constructor is refactored THEN the system SHALL remove all conditional service creation logic (no `if service is None: create_default()` patterns)
7. WHEN services are registered THEN the system SHALL use factory functions or direct registration in the DI container stage (`src/core/app/stages/core_services.py`)

#### Technical Constraints

- DI container: Use `ServiceCollection` from `src/core/di/container.py`
- Interface location: `src/core/interfaces/` directory
- Registration location: `src/core/di/services.py` or stage files in `src/core/app/stages/`

### Requirement 3: Public API Preservation

**Objective:** As a developer, I want the public API of BackendService to remain unchanged, so that existing code continues to work without modification.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. WHEN the refactoring is complete THEN the `IBackendService` interface SHALL remain unchanged (no method signature modifications)
2. WHEN the refactoring is complete THEN the `call_completion` method signature SHALL remain unchanged
3. WHEN the refactoring is complete THEN the `chat_completions` method signature SHALL remain unchanged
4. WHEN the refactoring is complete THEN the `validate_backend_and_model` method signature SHALL remain unchanged
5. WHEN the refactoring is complete THEN the `get_backend` method signature SHALL remain unchanged
6. WHEN the refactoring is complete THEN the `get_active_backends` method signature SHALL remain unchanged
7. WHEN helper methods are extracted THEN BackendService SHALL retain existing private helper methods (`_stream_as_sse_bytes`, `_wrap_stream_for_usage`, `_apply_model_aliases`, `_apply_reasoning_config`, `_apply_uri_parameters`, `_normalize_provider_exception`, etc.) as thin delegating wrappers so existing tests and scripts do not require changes
8. WHEN methods are delegated THEN the system SHALL preserve observable behavior and return values identical to the current implementation

#### Technical Constraints

- Interface location: `src/core/interfaces/backend_service.py`
- Backward compatibility: All existing callers must work without modification
- Test compatibility: Existing tests must pass without modification

### Requirement 4: Test Coverage and Regression Prevention

**Objective:** As a developer, I want the refactored code to maintain full test coverage, so that I can be confident the refactoring introduces no regressions.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. WHEN the refactoring is complete THEN the system SHALL pass all existing unit tests in `tests/unit/core/services/test_backend_service*.py` without modification
2. WHEN the refactoring is complete THEN the system SHALL pass all existing integration tests that use BackendService without modification
3. WHEN new services are created THEN the system SHALL include unit tests for each new service in `tests/unit/core/services/`
4. WHEN the refactoring is complete THEN the test suite SHALL achieve zero test failures
5. WHEN responsibilities are extracted THEN the system SHALL create characterization tests for extracted services to verify behavior preservation
6. WHEN helper methods are delegated THEN the system SHALL verify that delegation preserves observable invariants and side effects

#### Technical Constraints

- Test framework: pytest with markers defined in `pyproject.toml`
- Test location: `tests/unit/core/services/` for unit tests
- Test execution: `./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_backend_service*.py`

### Requirement 5: Backend Lifecycle Management Extraction

**Objective:** As a developer, I want backend lifecycle management to be isolated, so that backend creation, caching, and per-session limits can be managed independently.

**Priority:** P1 (High)

#### Acceptance Criteria

1. WHEN a BackendLifecycleManager service is created THEN the system SHALL provide a method to get or create backend instances with caching
2. WHEN a BackendLifecycleManager service is created THEN the system SHALL enforce per-session backend limits
3. WHEN a BackendLifecycleManager service is created THEN the system SHALL handle backend instance lifecycle (creation, caching, cleanup)
4. WHEN a BackendLifecycleManager service is created THEN the system SHALL resolve per-session backend limits from configuration
5. WHEN backend lifecycle logic is extracted THEN BackendService SHALL delegate `_get_or_create_backend` calls to BackendLifecycleManager
6. WHEN backend lifecycle logic is extracted THEN BackendService SHALL delegate `_resolve_per_session_backend_limit` calls to BackendLifecycleManager

#### Technical Constraints

- Interface: `IBackendLifecycleManager` in `src/core/interfaces/`
- Existing service: May already exist but needs integration verification
- Configuration: Must respect CLI > ENV > YAML precedence

### Requirement 6: Failover Coordination Extraction

**Objective:** As a developer, I want failover coordination logic to be isolated, so that failover strategies can be tested and modified independently.

**Priority:** P1 (High)

#### Acceptance Criteria

1. WHEN failover coordination is extracted THEN the system SHALL separate failover plan generation logic (`_get_failover_plan`) into a dedicated service
2. WHEN failover coordination is extracted THEN the system SHALL separate unhealthy backend filtering logic (`_filter_unhealthy_backends`) into a dedicated service
3. WHEN failover coordination is extracted THEN the system SHALL separate complex failover execution logic (`_execute_complex_failover`, `_attempt_failover_plan`) into a dedicated service
4. WHEN failover coordination is extracted THEN the system SHALL maintain integration with existing `IFailoverCoordinator` interface
5. WHEN failover logic is extracted THEN BackendService SHALL delegate failover operations to the failover coordinator service

#### Technical Constraints

- Interface: `IFailoverCoordinator` in `src/core/interfaces/failover_interface.py`
- Existing service: `FailoverCoordinator` may already exist but needs integration verification
- Integration: Must work with `FailoverService` and `BackendRoutingService`

### Requirement 7: Backend and Model Resolution Extraction

**Objective:** As a developer, I want backend and model resolution logic to be isolated, so that routing decisions can be tested and modified independently.

**Priority:** P1 (High)

#### Acceptance Criteria

1. WHEN backend and model resolution is extracted THEN the system SHALL separate `_resolve_backend_and_model` logic into a dedicated BackendModelResolver service
2. WHEN backend and model resolution is extracted THEN the system SHALL separate request synchronization logic (`_synchronize_request_with_target`) into the resolver service
3. WHEN backend and model resolution is extracted THEN the system SHALL integrate with existing `BackendRoutingService` and `ModelAliasResolver`
4. WHEN resolution logic is extracted THEN BackendService SHALL delegate resolution calls to the BackendModelResolver service
5. WHEN resolution logic is extracted THEN the system SHALL preserve existing routing behavior and model alias transformations

#### Technical Constraints

- Integration: Must work with `BackendRoutingService` and `ModelAliasResolver`
- Configuration: Must respect backend config provider and routing service settings
- Error handling: Must preserve existing error types and messages

### Requirement 8: Request Transformation Extraction

**Objective:** As a developer, I want request transformation logic to be isolated, so that model aliases, reasoning config, and URI parameters can be applied independently.

**Priority:** P1 (High)

#### Acceptance Criteria

1. WHEN request transformation is extracted THEN the system SHALL create a RequestTransformer service that coordinates model alias application, reasoning config application, and URI parameter application
2. WHEN request transformation is extracted THEN the system SHALL integrate with existing `ModelAliasResolver`, `ReasoningConfigApplicator`, and `URIParameterApplicator` services
3. WHEN request transformation is extracted THEN BackendService SHALL delegate `_apply_model_aliases`, `_apply_reasoning_config`, and `_apply_uri_parameters` calls to RequestTransformer
4. WHEN transformation logic is extracted THEN the system SHALL preserve the order of transformations (aliases → reasoning → URI parameters)
5. WHEN transformation logic is extracted THEN the system SHALL preserve existing transformation behavior and side effects

#### Technical Constraints

- Integration: Must coordinate with `ModelAliasResolver`, `ReasoningConfigApplicator`, `URIParameterApplicator`
- Order preservation: Transformation order must match current implementation
- Error handling: Must preserve existing error types and messages

### Requirement 9: Stream Processing Extraction

**Objective:** As a developer, I want stream processing logic to be isolated, so that SSE encoding, chunk validation, and session ID resolution can be tested independently.

**Priority:** P1 (High)

#### Acceptance Criteria

1. WHEN stream processing is extracted THEN the system SHALL separate SSE encoding logic (`_stream_as_sse_bytes`) into a dedicated StreamProcessor service
2. WHEN stream processing is extracted THEN the system SHALL separate stream session ID resolution (`_resolve_stream_session_id`) into the StreamProcessor service
3. WHEN stream processing is extracted THEN the system SHALL separate completion token validation (`_is_valid_completion_token`) into the StreamProcessor service
4. WHEN stream processing is extracted THEN the system SHALL integrate with existing `IStreamFormattingService` and `IUsageTrackingWrapper`
5. WHEN stream processing is extracted THEN BackendService SHALL delegate stream processing calls to StreamProcessor
6. WHEN stream processing is extracted THEN the system SHALL preserve existing SSE encoding format and chunk handling behavior

#### Technical Constraints

- Integration: Must work with `IStreamFormattingService` and `IUsageTrackingWrapper`
- Format preservation: SSE encoding format must match current implementation
- Session handling: Stream session ID resolution must preserve existing behavior

### Requirement 10: Exception Normalization Extraction

**Objective:** As a developer, I want exception normalization logic to be isolated, so that provider-specific exceptions can be normalized independently.

**Priority:** P1 (High)

#### Acceptance Criteria

1. WHEN exception normalization is extracted THEN the system SHALL separate `_normalize_provider_exception` logic into a dedicated ExceptionNormalizer service
2. WHEN exception normalization is extracted THEN the system SHALL integrate with existing `IExceptionNormalizer` interface
3. WHEN exception normalization is extracted THEN BackendService SHALL delegate exception normalization calls to ExceptionNormalizer
4. WHEN exception normalization is extracted THEN the system SHALL preserve existing exception type mappings and error messages
5. WHEN exception normalization is extracted THEN the system SHALL preserve existing error hierarchy (BackendError, RateLimitExceededError, AuthenticationError, etc.)

#### Technical Constraints

- Interface: `IExceptionNormalizer` in `src/core/interfaces/exception_normalizer_interface.py`
- Error hierarchy: Must preserve `LLMProxyError` subclasses
- Provider mapping: Must preserve existing provider-to-exception mappings

### Requirement 11: Failure Strategy Execution Extraction

**Objective:** As a developer, I want failure strategy execution logic to be isolated, so that failure handling can be tested and modified independently.

**Priority:** P1 (High)

#### Acceptance Criteria

1. WHEN failure strategy execution is extracted THEN the system SHALL separate `_apply_failure_strategy` logic into a dedicated FailureStrategyExecutor service
2. WHEN failure strategy execution is extracted THEN the system SHALL integrate with existing `IFailureHandlingStrategy` interface
3. WHEN failure strategy execution is extracted THEN BackendService SHALL delegate failure strategy calls to FailureStrategyExecutor
4. WHEN failure strategy execution is extracted THEN the system SHALL preserve existing failure decision logic and retry behavior
5. WHEN failure strategy execution is extracted THEN the system SHALL preserve integration with resilience coordinator and failover coordinator

#### Technical Constraints

- Interface: `IFailureHandlingStrategy` in `src/core/interfaces/failure_strategy_interface.py`
- Integration: Must work with `IResilienceCoordinator` and `IFailoverCoordinator`
- Decision preservation: Failure decisions must match current implementation

### Requirement 12: Code Organization and Maintainability

**Objective:** As a developer, I want the refactored code to be well-organized and maintainable, so that future changes are easier to implement.

**Priority:** P2 (Medium)

#### Acceptance Criteria

1. WHEN the refactoring is complete THEN BackendService SHALL be reduced to less than 500 lines of code (orchestration only)
2. WHEN the refactoring is complete THEN each extracted service SHALL have a single, clear responsibility
3. WHEN the refactoring is complete THEN each extracted service SHALL be independently testable
4. WHEN the refactoring is complete THEN the system SHALL follow consistent naming conventions across all extracted services
5. WHEN the refactoring is complete THEN the system SHALL have clear separation between orchestration (BackendService) and implementation (extracted services)
6. WHEN the refactoring is complete THEN the system SHALL have comprehensive docstrings for all public methods and classes

#### Technical Constraints

- Code organization: Follow patterns in `src/core/services/` directory
- Documentation: Use Python docstrings following project conventions
- Naming: Follow `PascalCase` for classes, `snake_case` for methods

## Non-Functional Requirements

### NFR 1: Performance

- Response latency: Refactoring SHALL not introduce measurable latency overhead (< 1ms per request)
- Streaming first-byte: Refactoring SHALL not delay first byte of streaming responses
- Throughput: Refactoring SHALL maintain existing request throughput capabilities

### NFR 2: Reliability

- Backend failover: Refactoring SHALL preserve existing failover behavior and timing
- Error handling: Refactoring SHALL preserve existing error handling and recovery mechanisms
- Rate limiting: Refactoring SHALL preserve existing rate limiting behavior

### NFR 3: Observability

- Wire captures: Refactoring SHALL preserve existing wire capture behavior and format
- Logging: Refactoring SHALL preserve existing logging levels and messages
- Health checks: Refactoring SHALL not affect health check endpoints

### NFR 4: Security

- API key handling: Refactoring SHALL preserve existing API key redaction and security measures
- Input validation: Refactoring SHALL preserve existing input validation boundaries
- Authentication: Refactoring SHALL preserve existing authentication requirements

## Out of Scope

- Modifying the public API of BackendService
- Changing the behavior of existing features
- Adding new features or capabilities
- Modifying the wire capture format
- Changing the error hierarchy or exception types
- Modifying configuration schemas or precedence
