# Requirements Document

## Introduction

This specification defines the requirements for refactoring `src/core/services/tool_call_reactor_middleware.py`, a high-complexity “God Object” module (currently ~1600 LOC, high cyclomatic complexity). The refactor must preserve existing runtime behavior while restructuring the implementation into smaller, focused components aligned with the project’s staged initialization and DI architecture. The refactored subsystem must be easier to test and debug, enforce strict cross-layer boundaries, and comply with SOLID and DRY principles without introducing a new “God object” elsewhere.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers maintaining the response-processing pipeline and tool policy logic
- Operators relying on stable proxy behavior and observability during tool execution
- Client integrations expecting consistent tool-call behavior across streaming and non-streaming

## Requirements

### Requirement 1: Preserve Public Contract and Behavioral Compatibility
**Objective:** As a maintainer, I want the tool-call reactor integration to behave identically after refactor, so that existing clients, backends, and policies keep working without regressions.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1.1 When `bypass_tool_call_reactor` is set in the response-processing context, the Tool Call Reactor subsystem shall not invoke the configured `IToolCallReactor` and shall return the input response unchanged.
1.2 When a response indicates `vtc_tool_calls` in its metadata, the Tool Call Reactor subsystem shall not invoke the configured `IToolCallReactor` and shall return the input response unchanged.
1.3 When the Tool Call Reactor subsystem receives a response that contains no tool calls, the Tool Call Reactor subsystem shall return the input response unchanged.
1.4 When the Tool Call Reactor subsystem receives a response that contains one or more tool calls, the Tool Call Reactor subsystem shall invoke the configured `IToolCallReactor` for each newly detected tool call.
1.5 If the configured `IToolCallReactor` returns a result indicating the tool call should be swallowed, the Tool Call Reactor subsystem shall return a replacement response consistent with the current externally observable behavior.
1.6 The Tool Call Reactor subsystem shall preserve backward compatibility for the legacy `ToolCallReactorMiddleware` entry point for existing wiring paths.

#### Technical Constraints
- Async compatibility: The Tool Call Reactor subsystem shall operate correctly in async FastAPI request flows.
- DI integration: Collaborators used by the Tool Call Reactor subsystem shall be injectable and resolvable via the project DI container.
- Error hierarchy: Failures surfaced outside the subsystem shall use the project exception model rooted at `LLMProxyError`.

### Requirement 2: Streaming and Non-Streaming Parity
**Objective:** As an operator, I want equivalent tool-call behavior across streaming and non-streaming responses, so that policies and outcomes do not depend on response mode.

**Priority:** P0 (Critical)

#### Acceptance Criteria
2.1 When a non-streaming response is processed, the Tool Call Reactor subsystem shall not retain per-stream detection state that would affect subsequent non-streaming requests.
2.2 While a streaming response is incomplete, the Tool Call Reactor subsystem shall not process tool calls that are not yet complete according to the current completion criteria.
2.3 When buffered tool calls are available for a streaming response, the Tool Call Reactor subsystem shall process buffered tool calls in the same order they were detected.
2.4 When the same tool call is detected multiple times within the same stream, the Tool Call Reactor subsystem shall process that tool call at most once per stream.
2.5 When tool calls are processed during streaming, the Tool Call Reactor subsystem shall apply the same swallow/replace behavior as in non-streaming mode.

#### Technical Constraints
- The Tool Call Reactor subsystem shall integrate with the response-processing pipeline interfaces (`IResponseFeature` / `IResponseMiddleware`) without changing their contracts.

### Requirement 3: Tool Call Detection and Normalization Robustness
**Objective:** As a maintainer, I want tool calls to be detected reliably across supported response shapes, so that backend/provider differences do not break tool handling.

**Priority:** P0 (Critical)

#### Acceptance Criteria
3.1 When tool calls are present on a response object via a `tool_calls` attribute, the Tool Call Reactor subsystem shall detect and normalize those tool calls.
3.2 When tool calls are present within response metadata, the Tool Call Reactor subsystem shall detect and normalize those tool calls.
3.3 When tool calls are encoded within response content, the Tool Call Reactor subsystem shall detect and normalize those tool calls consistent with the current behavior.
3.4 If an individual tool call cannot be normalized into the expected internal representation, the Tool Call Reactor subsystem shall skip that tool call without failing the entire response-processing operation.

#### Technical Constraints
- The Tool Call Reactor subsystem shall not require backend-specific imports in order to detect tool calls.

### Requirement 4: Tool Argument Parsing and Repair Behavior
**Objective:** As a developer, I want tool arguments to be parsed predictably and safely, so that tools receive usable inputs and failures are diagnosable.

**Priority:** P1 (High)

#### Acceptance Criteria
4.1 When a tool call includes arguments as valid JSON, the Tool Call Reactor subsystem shall provide the parsed argument value to downstream tool-call handling consistent with current behavior.
4.2 If a tool call includes arguments as invalid JSON, the Tool Call Reactor subsystem shall attempt best-effort recovery consistent with the current behavior and shall continue processing the response.
4.3 When tool argument recovery is attempted, the Tool Call Reactor subsystem shall record an outcome signal (success/recovered/failed) in a way that is observable to the configured `IToolCallReactor` when supported.
4.4 If tool arguments cannot be parsed or recovered, the Tool Call Reactor subsystem shall treat the arguments as absent and shall not crash the request.

#### Technical Constraints
- The Tool Call Reactor subsystem shall not log tool argument payloads at levels that would commonly be enabled in production when doing so could expose secrets.

### Requirement 5: Policy Steering and Safe Replacement Responses
**Objective:** As an operator, I want swallowed/blocked tool calls to result in safe and compliant assistant behavior, so that proxy policy enforcement is reliable and does not leak internal steering.

**Priority:** P0 (Critical)

#### Acceptance Criteria
5.1 When a tool call is swallowed by policy, the Tool Call Reactor subsystem shall produce a backend-facing steering message consistent with the current behavior when a custom replacement message is not provided.
5.2 When a tool call is swallowed by policy, the Tool Call Reactor subsystem shall not expose internal policy/steering text directly to the client response payload.
5.3 When a tool call is swallowed by policy, the Tool Call Reactor subsystem shall preserve enough original assistant content to support retries consistent with current behavior.
5.4 The Tool Call Reactor subsystem shall bound preserved swallowed content to a fixed maximum size consistent with the current behavior.

#### Technical Constraints
- The Tool Call Reactor subsystem shall preserve existing metadata signaling used by downstream response layers, where applicable.

### Requirement 6: Resilience and Failure Handling
**Objective:** As an operator, I want tool-call processing failures to fail open and remain observable, so that the proxy remains available and issues can be debugged.

**Priority:** P0 (Critical)

#### Acceptance Criteria
6.1 If an exception occurs during tool-call reactor execution for a tool call, the Tool Call Reactor subsystem shall log an error with exception details and shall continue processing subsequent tool calls or return the response without terminating the request.
6.2 If an exception occurs while extracting or normalizing tool calls, the Tool Call Reactor subsystem shall not crash the request and shall return the input response unchanged when no actionable tool calls can be produced.
6.3 When a tool call is successfully processed or fails during processing, the Tool Call Reactor subsystem shall mark that tool call as processed consistent with the current behavior to prevent repeated execution loops.

#### Technical Constraints
- Logging shall follow project structured logging patterns and include the session identifier when available.

### Requirement 7: Layered Architecture and Dependency Inversion
**Objective:** As a maintainer, I want the tool-call reactor implementation decomposed into well-bounded components, so that responsibilities are isolated, changes are safer, and tests are simpler.

**Priority:** P0 (Critical)

#### Acceptance Criteria
7.1 The Tool Call Reactor subsystem shall be decomposed so that each component has a single, clearly defined responsibility.
7.2 The Tool Call Reactor subsystem shall define stable, injectable interfaces at appropriate layer boundaries for components that need to be mocked in tests.
7.3 When the Tool Call Reactor subsystem is used within staged initialization, the Tool Call Reactor subsystem shall be constructible via DI without requiring global mutable state.
7.4 The Tool Call Reactor subsystem shall not introduce new cyclic dependencies across `src/core/interfaces/`, `src/core/services/`, and `src/core/domain/`.

#### Technical Constraints
- New cross-component dependencies shall depend on abstractions (`src/core/interfaces/`) rather than concrete implementations where test seams are required.

### Requirement 8: Refactor Quality Gates (Size and Complexity)
**Objective:** As a project owner, I want refactored code to stay below size/complexity limits, so that maintainability improves measurably.

**Priority:** P0 (Critical)

#### Acceptance Criteria
8.1 The Tool Call Reactor subsystem shall not contain any single Python source file exceeding 600 lines of code.
8.2 The Tool Call Reactor subsystem shall not contain any function or method with cyclomatic complexity of 50 or greater as measured by the project’s configured static analysis tooling.
8.3 The Tool Call Reactor subsystem shall not exceed the current public API surface area solely to accommodate refactoring (excluding new test seams and internal interfaces).

#### Technical Constraints
- These limits apply to production code produced or substantially modified as part of this refactor, excluding test files.

### Requirement 9: Testability and Regression Coverage
**Objective:** As a maintainer, I want strong automated coverage for the tool-call reactor behavior, so that refactoring can proceed safely and future changes are easier.

**Priority:** P1 (High)

#### Acceptance Criteria
9.1 When automated tests are executed for the tool-call reactor behavior, the test suite shall verify tool call detection from each supported response location (attribute, metadata, and content).
9.2 When automated tests are executed for streaming behavior, the test suite shall verify parity with non-streaming behavior for the same logical tool call sequence.
9.3 When automated tests are executed for policy swallowing behavior, the test suite shall verify that swallowed tool calls produce a replacement response and are not reprocessed.
9.4 When the full project test suite is executed, the refactor shall not introduce new test failures outside intentional, documented behavior changes.

#### Technical Constraints
- Tests shall be runnable under pytest using the repository’s standard commands and markers.

## Non-Functional Requirements

### Requirement 10: Maintainability and Debuggability
#### Acceptance Criteria
10.1 The Tool Call Reactor subsystem shall provide log messages sufficient to trace tool-call detection, skip/dedup decisions, and swallow/replace actions at DEBUG level.
10.2 If tool-call processing modifies the response, the Tool Call Reactor subsystem shall expose that decision via metadata or structured logs consistent with current behavior.

### Requirement 11: Reliability
#### Acceptance Criteria
11.1 If the Tool Call Reactor subsystem cannot access optional streaming state for a response, the Tool Call Reactor subsystem shall continue operating in a safe degraded mode without crashing the request.

### Requirement 12: Security and Privacy
#### Acceptance Criteria
12.1 The Tool Call Reactor subsystem shall not log secrets contained in tool arguments (for example API keys, tokens, or credentials) in INFO-level logs or higher.

## Glossary
| Term | Definition |
|------|------------|
| Tool Call | A model-emitted request to invoke a named tool/function with arguments. |
| Tool Call Reactor | The service (`IToolCallReactor`) that applies policy and handler logic to detected tool calls. |
| Tool Call Reactor Feature | The response feature (`IResponseFeature`) responsible for tool-call handling with streaming/non-streaming parity. |
| Tool Call Reactor Middleware | The legacy response middleware (`IResponseMiddleware`) entry point retained for backward compatibility. |
| Streaming Response | A response delivered as incremental chunks where completion may occur after multiple chunks. |
| Buffered Tool Calls | Tool calls detected and stored during streaming for later processing. |
| Swallowed Tool Call | A tool call that is blocked/consumed by policy and does not execute, replaced with steering behavior. |
| Steering Message | Backend-facing instruction used to guide the remote model after a tool call is swallowed. |
