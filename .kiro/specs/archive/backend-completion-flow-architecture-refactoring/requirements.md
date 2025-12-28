# Requirements Document

## Introduction

This document specifies requirements for a third iteration refactor of backend completion orchestration after `.kiro/specs/backend-service-god-object-refactoring`.

The current implementation is functional and tests are green, but architectural issues remain that make development and testing hard:
- Orchestration responsibilities are concentrated in a single very large module (`src/core/services/backend_completion_flow.py`).
- Transport/framework types are used in core/service code (for example `fastapi.HTTPException`), weakening layer boundaries.
- Test seams leak through production code (for example “parent service” compatibility shims).
- Temporary stub modules exist despite real implementations being present.

**Baseline (current code after the previous refactor)**:
- `src/core/services/backend_completion_flow.py` is 1953 lines (`wc -l`)
- `src/core/services/backend_service.py` is 689 lines (`wc -l`)
- `backend_completion_flow.py` max cyclomatic complexity is 23 (`scripts/analyze_complexity.py`)

**Primary goal (explicit):** This refactor is **NOT** intended to move responsibilities into a new god object / god module. It is intended to resolve the underlying architectural problems by introducing a properly layered, modular architecture with loose coupling and strong boundaries, applying SOLID principles and appropriate OOP design patterns to improve maintainability and testability while preserving behavior.

**Project Context**: Universal LLM Proxy - traffic routing, failover, accounting, and wire capture for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers maintaining backend orchestration and adding new behaviors (retry/failover, capture, accounting)
- Operators relying on predictable routing/failover behavior, observability, and stable wire-capture formats
- Users consuming OpenAI/Anthropic/Gemini-compatible APIs

## Glossary

- **Backend completion orchestration**: The subsystem that resolves target backend/model, prepares requests, invokes a backend, manages failover/retry decisions, integrates wire capture and usage tracking, and shapes responses (streaming and non-streaming).
- **Layer boundary**: A rule restricting dependencies between transport (FastAPI), application/services, domain models, and infrastructure.
- **God object / god module**: A single class/module accumulating unrelated responsibilities, increasing coupling and making local changes risky and difficult to test.
- **Transport/framework types**: Types owned by FastAPI/Starlette (for example `fastapi.HTTPException`) that should not leak into core/service logic.
- **Domain error model**: Exceptions rooted at `LLMProxyError` (`src/core/common/exceptions.py`) used for stable error semantics across layers.

## Requirements

### Requirement 1: Architectural Boundaries and Layering

**Objective:** As a developer, I want strict layer boundaries between FastAPI transport and backend orchestration logic, so that core behavior is testable and not coupled to HTTP frameworks.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1.1 When backend completion orchestration handles an error, the system shall represent it using the domain error model (`LLMProxyError` subclasses) rather than transport/framework exceptions.

1.2 The system shall not import FastAPI/Starlette types (for example `fastapi.HTTPException` or `starlette.*`) from core/service modules that implement backend completion orchestration.

1.3 When an error must be converted to an HTTP response, the system shall perform that conversion in the FastAPI adapter/controller layer rather than in core/service orchestration logic.

1.4 The system shall keep backend completion orchestration free of direct FastAPI request/response objects and shall operate on domain models (`ChatRequest`, `RequestContext`, `ResponseEnvelope`, `StreamingResponseEnvelope`).

#### Technical Constraints

- Async correctness: no blocking I/O in async paths.
- Error model: domain/service code raises `LLMProxyError` subclasses.
- Existing transport adapters remain responsible for mapping domain errors to HTTP responses.

### Requirement 2: True Decomposition (Avoid New God Objects/Modules)

**Objective:** As a developer, I want backend completion orchestration decomposed into cohesive collaborators with clear ownership, so that the system becomes easier to change and reason about without relocating complexity into a new single module.

**Priority:** P0 (Critical)

#### Acceptance Criteria

2.1 When the refactoring is complete, the system shall implement backend completion orchestration as a composition of focused collaborators with clearly separated responsibilities (for example: target resolution, backend invocation, wire capture orchestration, usage accounting, and failure-handling execution).

2.2 When the refactoring is complete, the system shall keep the top-level orchestration component as a coordinator that delegates substantial logic to collaborators rather than re-implementing the full decision tree in one place.

2.3 When the refactoring is complete, the system shall ensure no single service module introduced or modified for this refactor exceeds 1000 lines (`wc -l`) and no single method exceeds cyclomatic complexity 50 (`scripts/analyze_complexity.py`).

2.4 When the refactoring is complete, the system shall remove or replace “compatibility shims” that couple collaborators to legacy private methods (for example `parent_service` style delegation) with explicit interfaces and injection seams.

2.5 When the refactoring is complete, the top-level backend completion orchestration entrypoint module that implements `IBackendCompletionFlow` shall be ≤ 800 lines (`wc -l`), with substantive behavior delegated to collaborators.

2.6 When the refactoring is complete, each newly introduced collaborator implementation module in the backend completion orchestration subsystem shall be ≤ 500 lines (`wc -l`).

2.7 When the refactoring is complete, running `scripts/analyze_complexity.py` shall report `max_complexity ≤ 50` for every function/method in modules introduced or modified by this refactor, and `total_complexity ≤ 250` for each newly introduced collaborator module.

#### Technical Constraints

- Collaborators shall be in DI scope and constructed through the existing composition roots.
- Collaborators shall have small, focused interfaces in `src/core/interfaces/`.

### Requirement 3: Dependency Inversion and DI Consistency

**Objective:** As a developer, I want backend completion orchestration and its collaborators to depend on interfaces and to be wired consistently by DI, so that components are replaceable, mockable, and consistent across startup paths.

**Priority:** P0 (Critical)

#### Acceptance Criteria

3.1 The system shall construct backend completion orchestration and its collaborators via the DI container (`ServiceCollection` / `IServiceProvider`) without runtime fallback instantiation in constructors.

3.2 When services depend on other services, the system shall depend on interfaces from `src/core/interfaces/` rather than concrete implementations where practical.

3.3 When the application is constructed via either supported composition root (`register_core_services(...)` or staged fallback wiring in `src/core/app/stages/backend.py`), the system shall construct backend orchestration using the same explicit dependency set.

3.4 Where optional infrastructure services exist (for example wire capture, resilience coordinator, usage tracking), the system shall keep those dependencies optional without introducing branching that recreates dependencies internally.

#### Technical Constraints

- Staged init + DI: wiring continues to be owned by `src/core/di/services.py` and staged fallback factories.

### Requirement 4: Testability Without Production Boundary Leaks

**Objective:** As a developer, I want the backend completion orchestration subsystem to be testable via stable public seams rather than private-method mocking, so that tests remain robust across refactors.

**Priority:** P0 (Critical)

#### Acceptance Criteria

4.1 When the refactoring is complete, the system shall allow unit testing of failure-handling decisions by injecting a dedicated strategy interface rather than mocking private methods on unrelated services.

4.2 The system shall not require production-only compatibility parameters for tests (for example a “parent service” reference) to override behavior.

4.3 When tests need to vary behavior of a collaborator, the system shall support that variation by injecting a mocked interface implementation via DI/test builders rather than patching internal private attributes.

4.4 The system shall preserve (or replace with equivalent) existing test seams that validate routing, streaming behavior, failover decisions, and accounting decisions, without increasing reliance on implementation details.

#### Technical Constraints

- TDD: new collaborators introduced by this refactor shall have focused unit tests.

### Requirement 5: Behavior, Contract, and Invariant Preservation

**Objective:** As a developer and operator, I want this refactor to preserve all runtime behavior and public contracts, so that the refactor is safe and does not create operational regressions.

**Priority:** P0 (Critical)

#### Acceptance Criteria

5.1 The system shall preserve the `IBackendService` public contract (method names and signatures) and any externally observable API behavior mediated through it.

5.2 When wire capture is enabled, the system shall preserve capture behavior and existing CBOR wire format and attribution semantics.

5.3 When usage tracking is enabled, the system shall preserve usage tracking behavior, recorded values, and any ordering constraints that affect accounting.

5.4 When failover and retry behaviors apply, the system shall preserve current decision semantics (including complex failover recursion prevention and streaming “content started” safety behavior).

5.5 When the refactoring is complete, the system shall pass the full automated test suite (unit, integration, property) with zero failures.

#### Technical Constraints

- No changes to config schemas or precedence (CLI > ENV > YAML > defaults).
- No protocol/schema changes for OpenAI/Anthropic/Gemini endpoints.

### Requirement 6: Removal of Dead Code and Temporary Scaffolding

**Objective:** As a developer, I want temporary refactor scaffolding removed once real implementations exist, so that the codebase stays unambiguous and maintainable.

**Priority:** P1 (High)

#### Acceptance Criteria

6.1 When the refactoring is complete, the system shall not include unused stub implementations for backend completion orchestration collaborators in production modules.

6.2 The system shall not register temporary stub implementations in DI for production wiring paths when real implementations exist.

6.3 The system shall not use `type: ignore` to bypass access of private collaborator methods to preserve legacy tests, and shall instead provide explicit contracts where required.

### Requirement 7: Maintainability Gates and Change Locality

**Objective:** As a developer, I want maintainability gates and strong boundaries around orchestration concerns, so that future enhancements can be implemented by changing a single collaborator rather than editing a monolithic flow.

**Priority:** P2 (Medium)

#### Acceptance Criteria

7.1 When a new orchestration behavior is added (for example a new capture wrapper or a new failure policy), the system shall support implementing it by adding or extending a dedicated collaborator rather than modifying an unrelated subsystem.

7.2 The system shall provide a documented responsibility map for the backend completion orchestration subsystem, describing ownership boundaries and dependency directions, to reduce future refactor churn.

7.3 When the refactoring is complete, the system shall keep the complexity and size constraints in 2.3 enforceable by the repository’s existing tooling (`wc -l` and `scripts/analyze_complexity.py`).

### Requirement 8: Non-Functional Requirements

**Objective:** As a user and operator, I want the refactor to be safe and non-regressive, so that restructuring does not reduce performance, reliability, or security.

**Priority:** P2 (Medium)

#### Acceptance Criteria

8.1 The system shall not introduce measurable latency overhead for non-streaming requests attributable to orchestration restructuring (target: < 1ms per request in local benchmarks).

8.2 The system shall not delay first-byte time for streaming responses attributable to orchestration restructuring.

8.3 The system shall preserve existing resilience behavior (rate limiting, cooldowns, circuit breaker filtering, and failover fallback behaviors) without introducing new retry loops that change semantics.

8.4 The system shall preserve existing security properties: API key handling/redaction, input validation boundaries, and authentication/authorization behavior.

## Out of Scope

- Adding new user-facing features or changing observable behavior.
- Changing API schemas, config schemas, or config precedence.
- Changing wire capture format or capture storage layout.
- Refactoring unrelated large modules outside the backend completion orchestration boundary.

## Execution Guardrails (Agent Instructions)

These guardrails are **non-functional process constraints** intended to prevent repeating prior refactor failure modes. They are additive to the requirements above and are treated as non-negotiable constraints during implementation.

### Must Avoid

- Do not introduce a new “replacement orchestrator” by moving responsibilities from `BackendCompletionFlow` into another single class/module/package that becomes the new aggregation point.
- Do not keep “temporary” compatibility shims (for example “parent service” references, legacy private-method delegation hooks, or test-only constructor flags) in production services.
- Do not use private-method reach-through (`obj._private_method`) across collaborator boundaries to preserve legacy tests; replace with explicit contracts.
- Do not import or raise FastAPI/Starlette types from core/service orchestration modules; normalize to domain errors and let transport map to HTTP.
- Do not add runtime fallback instantiation patterns in constructors (“if dep is None create default”); DI owns construction.
- Do not leave placeholder/stub implementations in production code once real implementations exist.

### Mandatory Verification (Before marking any task complete)

- Run the relevant focused tests for the changed collaborator(s), then run the full automated test suite with zero failures.
- Verify size/complexity gates using `wc -l` and `scripts/analyze_complexity.py` for all modules introduced or modified by this refactor.
