# Requirements Document

## Introduction

This specification defines requirements for refactoring the `RequestProcessor` implementation in `src/core/services/request_processor_service.py` to eliminate the God Object anti-pattern and reduce SOLID violations. The refactoring decomposes the current monolithic orchestration logic into focused, single-responsibility components while preserving externally observable behavior (interfaces, return types, side effects, and tests).

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers maintaining and extending the request processing pipeline
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications

## Requirements

### 1. Compatibility and External Behavior Preservation
**Objective:** As a developer, I want the refactoring to preserve the current external behavior of request processing, so that existing clients, controllers, and tests continue to work unchanged.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1.1 When `IRequestProcessor.process_request` is called with `request_data` that is not a `ChatRequest`, the Request Processor Service shall raise `TypeError`.
1.2 When `process_request` is called with a `ChatRequest`, the Request Processor Service shall attach the request to the `RequestContext` as `domain_request` for downstream session resolution.
1.3 When command execution results in an early return (e.g., command-only flows), the Request Processor Service shall return the same envelope type and content shape as the current implementation.
1.4 When the backend call path is taken, the Request Processor Service shall return the backend response envelope without additional transformation.
1.5 When the backend call path is taken, the Request Processor Service shall update session history via the session manager using the same inputs as the current implementation.
1.6 When the backend call path is taken, and the session manager exposes fingerprint update, the Request Processor Service shall attempt fingerprint updates and shall not block the request if the fingerprint update fails.
1.7 When model replacement state exists, the Request Processor Service shall complete the model replacement turn in a `finally` block so that completion happens even on errors.

#### Technical Constraints
- Interface preservation: `IRequestProcessor` must remain unchanged.
- Return types: Must remain `ResponseEnvelope | StreamingResponseEnvelope`.
- Error hierarchy: Must preserve current exception types and propagation behavior.

### 2. Decomposition and SOLID Boundary Enforcement
**Objective:** As a developer, I want the request processing pipeline decomposed into cohesive components, so that responsibilities are isolated, testable, and aligned with SOLID and the layered architecture.

**Priority:** P0 (Critical)

#### Acceptance Criteria
2.1 When RequestProcessor is initialized, the Request Processor Service shall be composed of focused components rather than implementing all responsibilities directly.
2.2 The Request Processor Service shall ensure each extracted component has a single responsibility aligned to one phase of the request pipeline (session enrichment, context augmentation, command processing, request preparation, request transformations, backend execution).
2.3 When adding or changing one concern (e.g., tool filtering), the refactoring shall avoid changes to unrelated concerns (e.g., artifact preview expansion).
2.4 The Request Processor Service shall ensure extracted components depend on abstractions (interfaces/protocols) rather than concretions when interacting across layers.

#### Technical Constraints
- DI integration: Components must be registerable via the existing DI patterns used by the project.
- Async compatibility: All I/O paths must remain `async/await` compatible.

### 3. Complexity and Maintainability Targets
**Objective:** As a developer, I want the main orchestration logic significantly simplified, so that the codebase becomes easier to reason about, review, and evolve safely.

**Priority:** P0 (Critical)

#### Acceptance Criteria
3.1 When the refactoring is complete, `RequestProcessor.process_request` shall be an orchestration method that delegates to extracted components, not a method that implements business logic inline.
3.2 The refactoring shall ensure no single method in the request processing implementation exceeds 100 lines.
3.3 The refactoring shall include a repeatable complexity measurement approach that can run in this repository to validate complexity reduction (tool choice/configuration documented in the refactoring work, not in requirements).

#### Technical Constraints
- Maintainability: Avoid introducing new God Objects (e.g., a “pipeline manager” that simply relocates complexity).

### 4. Session and Client Context Enrichment
**Objective:** As a developer, I want session resolution and client context enrichment isolated, so that session-related logic is cohesive and changes do not spill into other phases.

**Priority:** P1 (High)

#### Acceptance Criteria
4.1 When a request is received, the Request Processor Service shall resolve the session ID via the session manager using the current `RequestContext`.
4.2 When a session agent is resolved, the Request Processor Service shall update the request agent field to match the session agent.
4.3 When the session state has no `client_os`, the Request Processor Service shall attempt OS detection from request messages and update session state when detected.
4.4 When OS detection cannot determine a value or encounters unexpected input, the Request Processor Service shall return “no detection” without raising.
4.5 When OS is available, the Request Processor Service shall populate `client_os` in the processing context for downstream middleware.
4.6 When VTC detection is enabled by configuration and not yet enabled in the session, the Request Processor Service shall evaluate the current agent against configured VTC patterns and enable VTC mode when matched.
4.7 When VTC mode is enabled in session state, the Request Processor Service shall propagate the VTC flag onto the request for downstream processors.
4.8 When project directory auto-resolution is eligible, the Request Processor Service shall attempt project directory resolution and shall not block request processing when resolution fails.

#### Technical Constraints
- OS detection: Must preserve existing heuristics (system info pattern and Windows path pattern) and multimodal text handling.
- Fail-open: Project directory resolution and VTC detection are best-effort and must not block.

### 5. Context Augmentation Side Effects (Streaming and Memory)
**Objective:** As a developer, I want non-domain side effects (streaming tool registry, memory context injection/capture) isolated, so that they can evolve independently from core request logic.

**Priority:** P1 (High)

#### Acceptance Criteria
5.1 When tools are present on the inbound request, the Request Processor Service shall register the list of allowed tool names in the global streaming context registry for the current session.
5.2 When tool name registration fails, the Request Processor Service shall log a warning and proceed without blocking request processing.
5.3 When memory context injection is enabled, the Request Processor Service shall attempt to inject context into the request after project directory resolution.
5.4 When memory context injection fails, the Request Processor Service shall log a warning and proceed without blocking request processing.
5.5 When memory capture is enabled, the Request Processor Service shall capture the request interaction prior to command processing.
5.6 When memory capture fails, the Request Processor Service shall log a warning and proceed without blocking request processing.

#### Technical Constraints
- Ordering: Project directory resolution must precede context injection; capture occurs before command processing.

### 6. Command Processing and Early Returns
**Objective:** As a developer, I want command processing behavior isolated and preserved, so that command parsing and command-only flows remain reliable during refactoring.

**Priority:** P1 (High)

#### Acceptance Criteria
6.1 When global command disabling is enabled, the Request Processor Service shall skip command processing and proceed to backend processing.
6.2 When command processing is enabled, the Request Processor Service shall delegate message processing to the command processor and obtain a `ProcessedResult`.
6.3 When a command-only path is detected, the Request Processor Service shall record the command in session history and return a command result response without calling the backend.
6.4 When the “Cline agent fast-path” conditions are met, the Request Processor Service shall return a command result response without calling the backend.
6.5 When the command processor indicates commands were executed, the Request Processor Service shall run artifact preview normalization on the resulting messages.

#### Technical Constraints
- Command processing: Must continue to use the existing command processor interface and `ProcessedResult` structure.

### 7. Tool Artifact Preview Expansion and Compression
**Objective:** As a developer, I want artifact preview handling extracted and preserved, so that tool output truncation handling remains correct and testable independently.

**Priority:** P2 (Medium)

#### Acceptance Criteria
7.1 When the most recent tool outputs contain a truncation marker with an artifact path, the Request Processor Service shall expand the referenced artifact into a bounded preview.
7.2 When older expanded previews exist outside the most recent tool message batch, the Request Processor Service shall compress those previews to preserve context window.
7.3 When artifact reading fails or a path is missing/unresolvable, the Request Processor Service shall skip expansion without raising.
7.4 When artifact paths are Windows paths in a non-Windows runtime, the Request Processor Service shall convert paths to an accessible form when possible.

#### Technical Constraints
- Limits: Must preserve existing max-line/max-char limits for preview and compression.
- Message formats: Must support both dict messages and Pydantic model messages.

### 8. Backend Request Preparation and Validation
**Objective:** As a developer, I want request preparation and validation isolated, so that backend-facing request shaping is cohesive and robust.

**Priority:** P1 (High)

#### Acceptance Criteria
8.1 When a backend request is prepared, the Request Processor Service shall delegate to the backend request manager to produce the backend request.
8.2 When configured model/token limits are available, the Request Processor Service shall enforce input token and total token limits using the existing token counting utilities.
8.3 If the input token limit is exceeded, then the Request Processor Service shall raise `InvalidRequestError` with the current structured fields.
8.4 If the total token limit is exceeded, then the Request Processor Service shall raise `InvalidRequestError` with a suggestion for reducing output tokens.
8.5 When validation encounters unexpected errors, the Request Processor Service shall treat enforcement as best-effort and proceed without blocking.

#### Technical Constraints
- Fail-fast: Structured `InvalidRequestError` must propagate.
- Fail-open: Unexpected validation errors must not block request processing.

### 9. Request Transformation Pipeline (Redaction, Precision, Tool Filtering)
**Objective:** As a developer, I want request transformations extracted into a clear pipeline, so that the system remains extensible while preserving current behavior and ordering.

**Priority:** P1 (High)

#### Acceptance Criteria
9.1 When API key redaction is enabled by configuration/session state, the Request Processor Service shall apply redaction to outbound requests before backend execution.
9.2 When API key redaction is disabled by session state, the Request Processor Service shall not instantiate or run redaction middleware.
9.3 When edit-precision tuning is enabled, the Request Processor Service shall apply request parameter adjustments following current configuration and agent exclusions.
9.4 When hybrid reasoning suppression is active for a session, the Request Processor Service shall apply a temporary hybrid reasoning probability override on the outbound request.
9.5 When tool filtering is enabled and tools are present, the Request Processor Service shall filter tool definitions and update tool choice when the referenced tool is removed.
9.6 When tool filtering removes tools, the Request Processor Service shall add tool filtering metadata to the outbound request extra body.
9.7 When any request transformation step fails unexpectedly, the Request Processor Service shall log and proceed without blocking request processing.
9.8 The request transformation pipeline shall preserve the current execution order: redaction, then edit precision, then tool filtering.

#### Technical Constraints
- Fail-open: Redaction, edit precision, and tool filtering remain non-blocking on unexpected errors.
- Config precedence: Preserve current precedence for redaction command prefix resolution (session override, app state, config).

### 10. Backend Execution and Session Persistence
**Objective:** As a developer, I want backend execution and its required side effects isolated, so that the core pipeline remains understandable and safe to modify.

**Priority:** P0 (Critical)

#### Acceptance Criteria
10.1 When a backend request exists, the Request Processor Service shall add the current session ID into the outbound request extra body if absent and ensure the request carries the session ID.
10.2 When a backend request exists, the Request Processor Service shall call the backend request manager with the current session ID and request context.
10.3 When backend execution completes, the Request Processor Service shall update session history using the original request, outbound request, backend response, and session ID.
10.4 When backend execution raises errors, the Request Processor Service shall propagate those errors without changing their type.

#### Technical Constraints
- Ordering: Tool filtering must run before adding the final session ID fields and before backend execution.

### 11. Dependency Injection Integration
**Objective:** As a developer, I want the new components to integrate with existing DI patterns, so that the system wiring remains consistent and test-friendly.

**Priority:** P0 (Critical)

#### Acceptance Criteria
11.1 The refactoring shall preserve that `IRequestProcessor` resolves to the concrete RequestProcessor implementation in the staged initialization container.
11.2 The refactoring shall preserve the ability to instantiate RequestProcessor directly in unit tests with minimal dependencies.
11.3 New components shall be registerable in the Processor stage using factory wiring consistent with existing patterns.
11.4 The refactoring shall avoid introducing service locator usage beyond what exists today, and shall prefer constructor injection for new dependencies.

#### Technical Constraints
- DI: Must remain compatible with both staged initialization (`ProcessorStage`) and existing container patterns used in older integration points.

### 12. Testing and Regression Safety
**Objective:** As a developer, I want the refactoring to be protected by tests, so that behavior is preserved and future modifications are safer.

**Priority:** P0 (Critical)

#### Acceptance Criteria
12.1 When existing tests are executed, the refactoring shall pass without requiring modifications to existing tests.
12.2 Extracted components shall have unit tests covering key happy paths and failure modes (fail-open vs fail-fast behavior).
12.3 The refactoring shall include integration coverage that exercises the full request pipeline through the existing controller/DI integration surfaces.

#### Technical Constraints
- Test framework: Must use pytest with existing markers and patterns.

## Non-Functional Requirements

### NFR 1: Performance
- Response latency: No material degradation in request processing time.
- Throughput: Maintain existing request/second capacity.

### NFR 2: Maintainability
- Code complexity: Reduce `RequestProcessor.process_request` complexity materially (target validated by the measurement approach defined during implementation).
- File size: Reduce the size of `src/core/services/request_processor_service.py` materially by extracting cohesive components.
- Cognitive load: Reduce the number of independent concerns inside the `RequestProcessor` class.

### NFR 3: Testability
- Component testability: Extracted components are unit-testable with lightweight fakes/mocks.
- Regression safety: Maintain existing coverage and preserve behavior under existing test suite.

### NFR 4: Extensibility
- Middleware addition: Adding a new request transformation step should not require modifying unrelated phases of the pipeline.

## Glossary

| Term | Definition |
|------|------------|
| RequestProcessor | Service implementing `IRequestProcessor` and orchestrating request processing |
| RequestContext | Transport-agnostic context containing headers, cookies, state, and app state |
| ProcessedResult | Domain model representing command processing results |
| Request transformations | Outbound request changes (redaction, precision tuning, tool filtering) |
| Command-only flow | A request flow where command execution returns a response without backend execution |
