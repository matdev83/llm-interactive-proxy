# Requirements Document

## Introduction

This document specifies requirements for refactoring `BackendService` (`src/core/services/backend_service.py`) to remove the “God Object” anti-pattern and SOLID violations while preserving all runtime behavior and external contracts.

**Baseline (current code)**:
- `src/core/services/backend_service.py` is 2109 lines (`wc -l`)
- `BackendService.call_completion` has cyclomatic complexity 180 (radon via `scripts/analyze_complexity.py`)
- Multiple responsibilities are mixed in a single class: backend/model target resolution, per-session backend selection, failover planning/execution, resilience and retry policy, usage tracking, wire capture integration, and streaming adaptation

**Project Context**: Universal LLM Proxy - traffic routing, failover, accounting, and wire capture for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers maintaining backend orchestration
- Operators relying on predictable routing/failover behavior and observability
- Users consuming OpenAI/Anthropic/Gemini-compatible APIs

## Glossary

- **BackendService**: `IBackendService` implementation that orchestrates backend calls, including failover, usage tracking, and optional wire capture.
- **God Object**: A class that owns too many unrelated responsibilities, making it hard to test, change, and reason about.
- **SOLID**: SRP, OCP, LSP, ISP, DIP.
- **DI container**: `ServiceCollection` / `IServiceProvider` wiring (`src/core/di/` and `src/core/di/services.py`).
- **Wire capture**: Byte-precise CBOR capture pipeline (`var/wire_captures_cbor/`) and related services.
- **Streaming**: Async iterator-based streaming, with SSE formatting via `IStreamFormattingService`.

## Requirements

### Requirement 1: God Object Mitigation and Maintainability Targets

**Objective:** As a developer, I want the BackendService responsibilities decomposed into focused collaborators, so that complexity is reduced without changing behavior.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1.1 When the refactoring is complete, the system shall move the bulk of completion orchestration out of `BackendService.call_completion` into a dedicated collaborator, leaving `BackendService.call_completion` as a thin delegating wrapper.

1.2 When the refactoring is complete, the system shall reduce the maximum cyclomatic complexity reported for `src/core/services/backend_service.py` to ≤ 25 and increase its maintainability index to ≥ 20 (as reported by `scripts/analyze_complexity.py`).

1.3 When the refactoring is complete, the system shall reduce `src/core/services/backend_service.py` to ≤ 500 lines (`wc -l`).

1.4 When new collaborators are introduced, the system shall ensure no new single method exceeds cyclomatic complexity 50 (radon CC) and no new service module exceeds 1000 lines.

#### Technical Constraints

- Async correctness: no blocking I/O in async paths.
- Staged init + DI: services registered through the existing DI composition root.
- Error model: domain/service code raises `LLMProxyError` subclasses.

### Requirement 2: Dependency Injection and Loose Coupling

**Objective:** As a developer, I want dependency construction to be centralized in DI wiring, so that BackendService and its collaborators do not instantiate their own dependencies.

**Priority:** P0 (Critical)

#### Acceptance Criteria

2.1 When the refactoring is complete, the system shall remove conditional dependency creation from `BackendService.__init__` (no “if dependency is None then create default” patterns).

2.2 When services depend on other services, the system shall depend on interfaces from `src/core/interfaces/` rather than concrete types where practical.

2.3 When the refactoring introduces new collaborators, the system shall register them and their interfaces in the existing DI composition root so production wiring does not rely on runtime fallbacks.

#### Technical Constraints

- DI implementation: `ServiceCollection` / `IServiceProvider`.
- Registration location: `src/core/di/services.py` (invoked by staged initialization).

### Requirement 3: Public Contract and Test Seam Preservation

**Objective:** As a developer, I want existing callers and tests to keep working, so that refactoring does not force behavior changes or widespread rewrites.

**Priority:** P0 (Critical)

#### Acceptance Criteria

3.1 When the refactoring is complete, `IBackendService` shall remain unchanged (method names and signatures).

3.2 When the refactoring is complete, the observable behavior of `call_completion`, `chat_completions`, `validate_backend_and_model`, `get_backend`, and `get_active_backends` shall remain unchanged.

3.3 When responsibilities are extracted, `BackendService` shall keep the existing helper methods that are referenced by tests as thin delegating wrappers with the same semantics, including:
- `_resolve_backend_and_model`
- `_synchronize_request_with_target`
- `_get_failover_plan`
- `_filter_unhealthy_backends`
- `_execute_complex_failover`
- `_attempt_failover_plan`
- `_apply_failure_strategy`
- `_stream_as_sse_bytes`
- `_resolve_stream_session_id`

3.4 When streaming is used, `BackendService._stream_as_sse_bytes` shall continue to produce the same SSE byte stream for the same input chunks.

### Requirement 4: Regression Prevention via Tests

**Objective:** As a developer, I want strong regression protection, so that behavior remains stable during large structural refactors.

**Priority:** P0 (Critical)

#### Acceptance Criteria

4.1 When the refactoring is complete, the system shall pass the full automated test suite (unit, integration, property, regression) with zero failures.

4.2 When core responsibilities are extracted, the system shall add characterization and unit tests that lock in behavior for backend/model resolution, failover planning/execution, streaming formatting, and failure-handling decisions.

### Requirement 5: Backend Lifecycle Boundaries

**Objective:** As a developer, I want backend instance lifecycle to remain owned by the lifecycle manager, so that caching and per-session behavior stay correct.

**Priority:** P1 (High)

#### Acceptance Criteria

5.1 When a backend instance is needed, the system shall use `IBackendLifecycleManager` for backend creation/caching and per-session backend limits.

5.2 If a backend is permanently disabled, the system shall preserve the existing fail-fast behavior and error messages (unless failover rules apply).

### Requirement 6: Backend and Model Target Resolution

**Objective:** As a developer, I want backend/model resolution to be isolated and testable, so that routing behavior can evolve without affecting unrelated concerns.

**Priority:** P1 (High)

#### Acceptance Criteria

6.1 When resolving request targets, the system shall preserve current resolution behavior: session-derived backend/model, parsing backend prefixes, parsing URI parameters, backend discovery/routing, and static route overrides.

6.2 When resolving request targets, the system shall preserve the current ordering constraint: model aliases are resolved before backend/model parsing and routing.

### Requirement 7: Failover Planning and Execution

**Objective:** As a developer, I want failover planning/execution isolated, so that complex failover behavior is testable and changes are localized.

**Priority:** P1 (High)

#### Acceptance Criteria

7.1 When failover planning is requested, the system shall preserve current behavior: use `IFailoverStrategy` when enabled, otherwise use `IFailoverCoordinator`, then apply health filtering when circuit breaker is enabled.

7.2 When filtering unhealthy backends, the system shall preserve current behavior: exclude permanently disabled backends, exclude unhealthy active backends, and fall back to the original plan when filtering would remove all options.

7.3 When complex failover routes apply, the system shall preserve current behavior: attempt the plan in order and prevent recursive re-entry into complex failover loops.

### Requirement 8: Streaming Session Identity DRY

**Objective:** As a developer, I want streaming session-id resolution logic centralized, so that capture/buffering uses consistent session identifiers and avoids duplication.

**Priority:** P1 (High)

#### Acceptance Criteria

8.1 When the system needs a stable session identifier for streaming capture/buffering, it shall apply a single shared algorithm used consistently across BackendService and buffered wire capture logic.

8.2 When session identifiers are missing, the system shall preserve current fallback behavior to a generated UUID.

### Requirement 9: Exception Normalization and Error Semantics

**Objective:** As a developer, I want provider exceptions normalized consistently, so that callers receive stable error types and messages.

**Priority:** P1 (High)

#### Acceptance Criteria

9.1 When provider exceptions are raised, the system shall preserve current normalization/mapping to domain errors (including `BackendError`, `RateLimitExceededError`, and `AuthenticationError`).

### Requirement 10: Failure Handling Strategy Semantics

**Objective:** As a developer, I want failure-handling decisions preserved, so that retry/failover behavior remains predictable.

**Priority:** P1 (High)

#### Acceptance Criteria

10.1 When a backend call fails, the system shall preserve current decision semantics derived from `IFailureHandlingStrategy` (retry wait, alternate backend selection, or surfacing the error).

### Requirement 11: Observability Preservation

**Objective:** As an operator, I want captures/logs/usage tracking preserved, so that refactoring does not reduce debuggability or accounting correctness.

**Priority:** P1 (High)

#### Acceptance Criteria

11.1 When wire capture is enabled, the system shall preserve current capture behavior and CBOR wire format.

11.2 When usage tracking is enabled, the system shall preserve current usage tracking behavior and recorded values.

### Requirement 12: Non-Functional Requirements

**Objective:** As a user and operator, I want refactoring to be safe, performant, and secure.

**Priority:** P2 (Medium)

#### Acceptance Criteria

12.1 The system shall not introduce measurable latency overhead for non-streaming requests (target: < 1ms per request in local benchmarks).

12.2 The system shall not delay first-byte time for streaming responses.

12.3 The system shall preserve existing security properties: API key handling/redaction, input validation boundaries, and authentication/authorization behavior.

## Out of Scope

- Adding new features or changing existing behavior
- Changing API schemas, config schemas, or config precedence
- Changing wire capture format or capture storage layout
- Refactoring unrelated God Objects outside the BackendService boundary
