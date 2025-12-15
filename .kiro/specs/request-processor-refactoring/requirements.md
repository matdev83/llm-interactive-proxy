# Requirements Document

## Introduction

This specification defines requirements for refactoring `request_processor_service.py` to eliminate God Object anti-pattern and SOLID principles violations. The refactoring will decompose the monolithic `RequestProcessor` class into focused, single-responsibility components while maintaining backward compatibility and improving testability.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers maintaining and extending the request processing pipeline
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications

## Requirements

### Requirement 1: Request Processor Decomposition
**Objective:** As a developer, I want the RequestProcessor to be decomposed into focused components, so that each component has a single, well-defined responsibility following SOLID principles.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When RequestProcessor is initialized, the Request Processor Service shall compose focused components instead of handling all responsibilities directly
2. When a request is processed, the Request Processor Service shall delegate session management to a dedicated SessionRequestHandler component
3. When a request is processed, the Request Processor Service shall delegate command processing to a dedicated CommandRequestHandler component
4. When a request is processed, the Request Processor Service shall delegate backend request preparation to a dedicated BackendRequestPreparator component
5. When a request is processed, the Request Processor Service shall delegate middleware application to a dedicated MiddlewareApplicator component
6. When a request is processed, the Request Processor Service shall delegate artifact processing to a dedicated ArtifactProcessor component
7. When a request is processed, the Request Processor Service shall delegate client detection to a dedicated ClientDetectionService component
8. When a request is processed, the Request Processor Service shall delegate project directory resolution to a dedicated ProjectDirectoryResolver component
9. The Request Processor Service shall maintain the existing `IRequestProcessor` interface contract
10. When RequestProcessor is instantiated, the Request Processor Service shall accept all existing constructor dependencies without breaking changes

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Interface preservation: `IRequestProcessor.process_request()` signature must remain unchanged

### Requirement 2: Middleware Chain Pattern Implementation
**Objective:** As a developer, I want middleware to be applied via a chain pattern, so that new middleware can be added without modifying core request processing logic.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When middleware is registered, the Middleware Chain Manager shall add it to an ordered chain
2. When a request is processed, the Middleware Chain Manager shall execute middleware in registration order
3. When middleware execution completes, the Middleware Chain Manager shall pass the processed request to the next middleware in the chain
4. When middleware execution fails, the Middleware Chain Manager shall handle the error and prevent request processing from continuing
5. When middleware needs to short-circuit processing, the Middleware Chain Manager shall support returning a response directly without backend call
6. Where middleware is optional, the Middleware Chain Manager shall skip unregistered middleware without errors
7. When middleware modifies the request, the Middleware Chain Manager shall pass the modified request to subsequent middleware
8. The Middleware Chain Manager shall support middleware that operates on both request and context
9. When middleware is disabled via configuration, the Middleware Chain Manager shall exclude it from the chain
10. The Middleware Chain Manager shall provide execution order control for middleware dependencies

#### Technical Constraints
- Middleware interface: Must implement `IRequestMiddleware` or compatible protocol
- Execution order: Must respect dependency ordering
- Error handling: Must propagate `LLMProxyError` subclasses appropriately
- Context passing: Must support `RequestContext` and custom context dictionaries

### Requirement 3: Complexity Reduction
**Objective:** As a developer, I want the `process_request()` method complexity reduced, so that the code is easier to understand, test, and maintain.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When `process_request()` is implemented, the Request Processor Service shall have cyclomatic complexity less than 20
2. When `process_request()` is implemented, the Request Processor Service shall delegate to focused handler components instead of implementing logic inline
3. When conditional logic is required, the Request Processor Service shall use strategy pattern or handler selection instead of nested conditionals
4. When error handling is required, the Request Processor Service shall use dedicated error handlers instead of inline try-except blocks
5. When validation is required, the Request Processor Service shall use dedicated validators instead of inline checks
6. The Request Processor Service shall maintain average method complexity below 10 across all methods
7. When a method exceeds complexity 15, the Request Processor Service shall be refactored to extract sub-methods or components
8. The Request Processor Service shall have no methods exceeding 100 lines of code

#### Technical Constraints
- Complexity measurement: Use radon CC metric
- Maintainability index: Target MI > 20 (currently 0.00)
- Code organization: Follow existing project structure patterns
- Test coverage: All extracted components must have unit tests

### Requirement 4: Session Management Extraction
**Objective:** As a developer, I want session management logic extracted to a dedicated component, so that session handling concerns are isolated and testable.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When a request is received, the Session Request Handler shall resolve session ID from context
2. When session ID is resolved, the Session Request Handler shall load session from session manager
3. When session agent differs from request agent, the Session Request Handler shall update session with incoming agent
4. When session state requires client OS detection, the Session Request Handler shall delegate to ClientDetectionService
5. When session state requires VTC detection, the Session Request Handler shall delegate to VTCDetectionService
6. When session state requires project directory resolution, the Session Request Handler shall delegate to ProjectDirectoryResolver
7. When session is updated, the Session Request Handler shall persist changes via session manager
8. The Session Request Handler shall handle session creation for new sessions
9. The Session Request Handler shall propagate session state to request context for downstream processing
10. When session operations fail, the Session Request Handler shall raise appropriate `LLMProxyError` subclasses

#### Technical Constraints
- Session interface: Must use `ISessionManager` interface
- State management: Must preserve existing session state behavior
- Error handling: Must not silently fail on session errors
- Context propagation: Must update `RequestContext` appropriately

### Requirement 5: Command Processing Extraction
**Objective:** As a developer, I want command processing logic extracted to a dedicated component, so that command handling is isolated and can be tested independently.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When a request contains commands, the Command Request Handler shall delegate processing to command processor
2. When commands are disabled globally, the Command Request Handler shall skip command processing
3. When command processing completes, the Command Request Handler shall return processed result with execution status
4. When command processing modifies messages, the Command Request Handler shall return modified messages in processed result
5. When command processing produces results, the Command Request Handler shall return command results in processed result
6. When command-only path is detected, the Command Request Handler shall signal that backend call should be skipped
7. When Cline agent expects tool_calls for proxy commands, the Command Request Handler shall handle special response formatting
8. The Command Request Handler shall handle artifact expansion for truncated tool outputs
9. When command processing fails, the Command Request Handler shall raise appropriate `LLMProxyError` subclasses
10. The Command Request Handler shall record command execution in session history

#### Technical Constraints
- Command interface: Must use `ICommandProcessor` interface
- Result format: Must return `ProcessedResult` domain model
- Artifact handling: Must preserve existing artifact expansion/compression behavior
- Session integration: Must record commands via `ISessionManager`

### Requirement 6: Backend Request Preparation Extraction
**Objective:** As a developer, I want backend request preparation logic extracted to a dedicated component, so that request transformation concerns are isolated.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When a request is prepared for backend, the Backend Request Preparator shall apply model replacement if configured
2. When model replacement is active, the Backend Request Preparator shall resolve effective backend and model
3. When context window limits are configured, the Backend Request Preparator shall enforce per-model limits
4. When input token limit is exceeded, the Backend Request Preparator shall raise `InvalidRequestError`
5. When total token limit is exceeded, the Backend Request Preparator shall raise `InvalidRequestError` with suggestion
6. When CLI context window override is set, the Backend Request Preparator shall apply override to limits
7. When backend request is prepared, the Backend Request Preparator shall delegate to BackendRequestManager for final preparation
8. The Backend Request Preparator shall handle model alias resolution
9. The Backend Request Preparator shall preserve request metadata during transformation
10. When request preparation fails, the Backend Request Preparator shall raise appropriate `LLMProxyError` subclasses

#### Technical Constraints
- Request interface: Must use `IBackendRequestManager` interface
- Token calculation: Must use existing token counting utilities
- Error types: Must use `InvalidRequestError` for validation failures
- Model resolution: Must preserve existing model resolution logic

### Requirement 7: Middleware Application Extraction
**Objective:** As a developer, I want middleware application logic extracted to a dedicated component, so that middleware concerns are isolated and extensible.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When a request is processed, the Middleware Applicator shall apply redaction middleware if enabled
2. When redaction middleware is applied, the Middleware Applicator shall redact API keys from request messages
3. When redaction middleware is applied, the Middleware Applicator shall redact proxy commands from request messages
4. When edit precision tuning is enabled, the Middleware Applicator shall apply EditPrecisionTuningMiddleware
5. When edit precision tuning is applied, the Middleware Applicator shall adjust temperature and top_p parameters
6. When hybrid reasoning override is required, the Middleware Applicator shall apply hybrid reasoning probability override
7. When tool access control is enabled, the Middleware Applicator shall filter tool definitions via ToolAccessPolicyService
8. When tool filtering removes tools, the Middleware Applicator shall update tool_choice appropriately
9. When middleware application fails, the Middleware Applicator shall log warning and continue without blocking request
10. The Middleware Applicator shall support conditional middleware application based on session state

#### Technical Constraints
- Middleware interface: Must use `IRequestMiddleware` or compatible protocol
- Error handling: Must be fail-open (log and continue)
- Configuration: Must respect app config and session overrides
- Tool filtering: Must integrate with `ToolAccessPolicyService`

### Requirement 8: Artifact Processing Extraction
**Objective:** As a developer, I want artifact processing logic extracted to a dedicated component, so that artifact handling concerns are isolated.

**Priority:** P2 (Medium)

#### Acceptance Criteria
1. When tool outputs contain truncated artifacts, the Artifact Processor shall expand artifact references to preview content
2. When artifact preview is expanded, the Artifact Processor shall limit preview to configured line and character limits
3. When artifact preview exceeds limits, the Artifact Processor shall truncate with omission markers
4. When previously expanded previews exist, the Artifact Processor shall compress them to preserve context
5. When artifact path is Windows format, the Artifact Processor shall convert to accessible path format
6. When artifact file does not exist, the Artifact Processor shall skip expansion without error
7. When artifact reading fails, the Artifact Processor shall log warning and skip expansion
8. The Artifact Processor shall identify trailing tool message indices for batch processing
9. The Artifact Processor shall preserve non-artifact tool messages unchanged
10. When artifact processing completes, the Artifact Processor shall return normalized messages

#### Technical Constraints
- Path handling: Must support Windows and Unix path formats
- File I/O: Must handle encoding errors gracefully
- Limits: Must use existing constants for max lines/chars
- Message format: Must preserve Pydantic model structure

### Requirement 9: Client Detection Extraction
**Objective:** As a developer, I want client detection logic extracted to a dedicated component, so that detection concerns are isolated and testable.

**Priority:** P2 (Medium)

#### Acceptance Criteria
1. When client OS is not detected, the Client Detection Service shall analyze request messages for OS indicators
2. When Windows path patterns are detected, the Client Detection Service shall return "windows" as OS
3. When macOS indicators are detected, the Client Detection Service shall return "macos" as OS
4. When Linux indicators are detected, the Client Detection Service shall return "linux" as OS
5. When no OS indicators are found, the Client Detection Service shall return None
6. When VTC client patterns match agent identifier, the Client Detection Service shall enable VTC mode
7. When VTC mode is enabled, the Client Detection Service shall update session state
8. The Client Detection Service shall handle multimodal message content for OS detection
9. The Client Detection Service shall extract OS info from system message content
10. When detection fails, the Client Detection Service shall return None without raising errors

#### Technical Constraints
- Pattern matching: Must use existing regex patterns
- Message parsing: Must handle both dict and Pydantic model formats
- State updates: Must use session state update methods
- Error handling: Must be fail-safe (return None on errors)

### Requirement 10: Backward Compatibility
**Objective:** As a developer, I want the refactored RequestProcessor to maintain backward compatibility, so that existing code and tests continue to work without changes.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When RequestProcessor is instantiated, the Request Processor Service shall accept all existing constructor parameters
2. When `process_request()` is called, the Request Processor Service shall accept existing `RequestContext` and `ChatRequest` parameters
3. When `process_request()` returns, the Request Processor Service shall return `ResponseEnvelope` or `StreamingResponseEnvelope` as before
4. When RequestProcessor is used in existing code, the Request Processor Service shall behave identically to current implementation
5. When existing tests run, the Request Processor Service shall pass all tests without modification
6. When interface contracts are preserved, the Request Processor Service shall maintain `IRequestProcessor` interface compliance
7. When error handling occurs, the Request Processor Service shall raise same exception types as current implementation
8. When logging occurs, the Request Processor Service shall produce same log messages and levels
9. When configuration is accessed, the Request Processor Service shall use same configuration sources and precedence
10. When session state is accessed, the Request Processor Service shall preserve existing session state structure

#### Technical Constraints
- Interface preservation: `IRequestProcessor` must remain unchanged
- Method signatures: All public methods must maintain existing signatures
- Return types: Must match existing return type annotations
- Exception types: Must raise same exception hierarchy
- Test compatibility: All existing tests must pass without modification

### Requirement 11: Testability Improvements
**Objective:** As a developer, I want the refactored components to be easily testable, so that unit tests can be written and maintained efficiently.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When a component is extracted, the Request Processor Service shall have clear interface boundaries for mocking
2. When a component is tested, the Request Processor Service shall support dependency injection for test doubles
3. When a component has dependencies, the Request Processor Service shall use interface types instead of concrete classes
4. When a component processes requests, the Request Processor Service shall have isolated testable units
5. When a component handles errors, the Request Processor Service shall have testable error paths
6. When a component uses configuration, the Request Processor Service shall support test configuration injection
7. When a component accesses session state, the Request Processor Service shall support mock session injection
8. When integration tests are written, the Request Processor Service shall support end-to-end testing with real dependencies
9. When unit tests are written, the Request Processor Service shall achieve coverage above 80% for new components
10. When test fixtures are created, the Request Processor Service shall follow existing test patterns and conventions

#### Technical Constraints
- Test framework: Must use pytest with existing markers
- Mocking: Must use pytest-mock or unittest.mock
- Coverage: Must maintain or improve existing coverage levels
- Test organization: Must follow existing test directory structure

### Requirement 12: Component Integration
**Objective:** As a developer, I want extracted components to integrate seamlessly, so that the request processing pipeline functions correctly end-to-end.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When RequestProcessor orchestrates components, the Request Processor Service shall coordinate execution in correct order
2. When session handling completes, the Request Processor Service shall pass results to command processing
3. When command processing completes, the Request Processor Service shall pass results to backend preparation
4. When backend preparation completes, the Request Processor Service shall pass results to middleware application
5. When middleware application completes, the Request Processor Service shall pass results to backend call
6. When backend call completes, the Request Processor Service shall pass results to response processing
7. When component execution fails, the Request Processor Service shall propagate errors appropriately
8. When component execution short-circuits, the Request Processor Service shall return early response without backend call
9. When component modifies request, the Request Processor Service shall pass modified request to next component
10. When component modifies context, the Request Processor Service shall pass modified context to next component

#### Technical Constraints
- Execution order: Must preserve existing processing order
- Data flow: Must maintain request and context state through pipeline
- Error propagation: Must preserve existing error handling behavior
- Short-circuiting: Must support early returns for command-only paths

## Non-Functional Requirements

### NFR 1: Performance
- Response latency: No degradation in request processing time
- Memory usage: No significant increase in memory footprint
- Throughput: Maintain existing request/second capacity

### NFR 2: Maintainability
- Code complexity: Reduce cyclomatic complexity from 214 to < 20 for `process_request()`
- File size: Reduce `request_processor_service.py` from 1485 lines to < 500 lines
- Maintainability index: Improve from 0.00 to > 20
- Component count: Extract 8-10 focused components from monolithic class

### NFR 3: Testability
- Unit test coverage: Achieve > 80% coverage for new components
- Integration test coverage: Maintain existing integration test coverage
- Test execution time: No significant increase in test suite execution time
- Mock complexity: Reduce mocking complexity through better interfaces

### NFR 4: Extensibility
- Middleware addition: Support adding new middleware without modifying core code
- Component extension: Support extending components via inheritance or composition
- Configuration: Support feature flags for enabling/disabling components
- Plugin architecture: Maintain ability to add new request processors

## Glossary

| Term | Definition |
|------|------------|
| RequestProcessor | Core service that orchestrates request processing pipeline |
| Session Request Handler | Component responsible for session resolution and state management |
| Command Request Handler | Component responsible for processing embedded commands |
| Backend Request Preparator | Component responsible for preparing requests for backend calls |
| Middleware Applicator | Component responsible for applying request transformation middleware |
| Artifact Processor | Component responsible for expanding/compressing tool output artifacts |
| Client Detection Service | Component responsible for detecting client OS and capabilities |
| Middleware Chain | Ordered sequence of middleware components executed in sequence |
| ProcessedResult | Domain model containing command processing results |
| RequestContext | Transport-agnostic context containing headers, cookies, and state |
| ChatRequest | Domain model representing a chat completion request |
| ResponseEnvelope | Domain model representing a non-streaming response |
| StreamingResponseEnvelope | Domain model representing a streaming response |
