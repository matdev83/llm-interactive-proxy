# Requirements Document

## Introduction

**Project Description**: Refactor the overly large `src/connectors/hybrid.py` (2,301 lines) God Object into a modular, layered architecture with proper SOLID compliance, loose coupling, strong cross-layer boundaries, and OOP design patterns - while preserving all public APIs and maintaining 100% passing test suite.

**Project Context**: Universal LLM Proxy - The hybrid connector orchestrates two-phase LLM interactions where a reasoning model generates chain-of-thought reasoning, which is then captured and injected into an execution model's context for enhanced responses.

**Stakeholders**:

- Developers maintaining and extending the hybrid backend functionality
- Operators configuring two-phase reasoning workflows
- Test maintainers ensuring code quality and coverage

---

## Requirements

### Requirement 1: Modular Package Structure

**Objective:** As a developer, I want the hybrid connector code decomposed into a modular package structure, so that I can understand, maintain, and extend individual concerns independently.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. When the hybrid backend package is created, the HybridConnector shall organize functionality into a `src/connectors/hybrid_backend/` package with clear submodule boundaries.

2. The hybrid_backend package shall contain distinct directories for: models (domain data types), services (business logic), orchestration (flow coordination), and infrastructure (external I/O adapters).

3. When a developer imports from the hybrid backend, the package `__init__.py` shall expose only public interfaces and orchestration entry points.

4. The HybridConnector class in `src/connectors/hybrid.py` shall remain as a thin facade delegating to the new modular package to preserve backward compatibility.

#### Technical Constraints

- Async compatibility: Must use `async/await` patterns throughout
- DI integration: New services should be injectable via `ServiceCollection` when appropriate
- Error hierarchy: Exceptions extend `LLMProxyError`

---

### Requirement 2: Single Responsibility Compliance

**Objective:** As a developer, I want each module to have a single, well-defined responsibility, so that changes to one concern do not require modifications across multiple unrelated files.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. The HybridConnector shall delegate model specification parsing to a dedicated `ModelSpecParser` service that handles only the `hybrid:[backend:model,backend:model]` format parsing.

2. The HybridConnector shall delegate parameter application to a dedicated `ParameterApplicator` service that handles only reasoning/execution phase parameter overrides.

3. The HybridConnector shall delegate message augmentation to a dedicated `MessageAugmentor` service that handles only injecting reasoning content into message lists.

4. The HybridConnector shall delegate reasoning markup processing to a dedicated `ReasoningMarkupProcessor` service that handles only tag normalization, wrapping, and extraction.

5. The HybridConnector shall delegate response filtering to a dedicated `ResponseFilter` service that handles only stripping reasoning tags from responses.

6. The HybridConnector shall delegate response building to a dedicated `ResponseBuilder` service that handles only constructing streaming/non-streaming response envelopes.

7. When any service is modified, the Hybrid Connector shall require no changes unless the service's public interface changes.

---

### Requirement 3: Protocol-First Design (Interface Segregation)

**Objective:** As a developer, I want each service to implement a well-defined Protocol interface, so that I can easily substitute implementations for testing and extension.

**Priority:** P1 (High)

#### Acceptance Criteria

1. The hybrid_backend package shall define a `protocols.py` module containing Python Protocol definitions for all service interfaces.

2. Each Protocol shall define only the methods relevant to that specific concern (no monolithic interfaces).

3. When creating service implementations, each service class shall explicitly implement its corresponding Protocol.

4. If a test needs to mock a hybrid backend component, then the test shall be able to provide a mock implementing only the specific Protocol interface.

5. The `@runtime_checkable` decorator shall be applied to all Protocol definitions to enable runtime type checking.

---

### Requirement 4: Dependency Inversion

**Objective:** As a developer, I want high-level orchestration code to depend on abstractions rather than concrete implementations, so that the system is loosely coupled and testable.

**Priority:** P1 (High)

#### Acceptance Criteria

1. The `HybridOrchestrator` shall receive all its dependencies (services, adapters) via constructor injection rather than creating them internally.

2. When resolving external services (e.g., `BackendService`, `BackendFactory`), the infrastructure layer shall use DI service resolution rather than direct imports within business logic.

3. If a new backend type is added, then the orchestration layer shall require no modifications (Open/Closed Principle compliance).

4. The orchestrator shall interact with phase executors through Protocol interfaces, not concrete classes.

---

### Requirement 5: Layered Architecture with Cross-Layer Boundaries

**Objective:** As a developer, I want clear architectural layers with enforced boundaries, so that dependencies flow in one direction and layers remain decoupled.

**Priority:** P1 (High)

#### Acceptance Criteria

1. The hybrid_backend package shall implement four layers: Facade (public API), Orchestration (business logic), Services (domain logic), and Infrastructure (external I/O).

2. Each layer shall only import from layers below it (Facade → Orchestration → Services/Infrastructure → Models).

3. The Models layer shall have no dependencies on other layers (pure data structures with stdlib/typing only).

4. When a layer violation occurs (e.g., Services importing from Orchestration), the architecture check shall fail.

5. While adding new functionality, the developer shall place code in the appropriate layer based on its responsibility type.

---

### Requirement 6: Domain Model Extraction

**Objective:** As a developer, I want reasoning phase data encapsulated in typed domain models, so that data contracts are explicit and type-safe.

**Priority:** P2 (Medium)

#### Acceptance Criteria

1. The `HybridModelSpec` dataclass shall be moved to `hybrid_backend/models/model_spec.py` with no logic beyond data representation.

2. The `ReasoningPhaseResult` dataclass shall be moved to `hybrid_backend/models/phase_result.py`.

3. A new `ReasoningText` dataclass shall be created to encapsulate tagged reasoning output and plain text representation as a single typed unit.

4. A new `InjectionDecision` dataclass shall be created to encapsulate injection decision state (should_inject, reason, probability).

5. All domain models shall use Python dataclasses with type hints and shall be immutable (frozen=True) where appropriate.

---

### Requirement 7: Orchestrator Extraction

**Objective:** As a developer, I want the main two-phase flow logic extracted into a dedicated orchestrator, so that the flow coordination is separated from individual phase implementations.

**Priority:** P1 (High)

#### Acceptance Criteria

1. The `HybridOrchestrator` class shall coordinate the two-phase reasoning-then-execution flow by composing injected services.

2. When `execute()` is called, the orchestrator shall: parse model spec, decide on injection, optionally execute reasoning phase, augment messages, execute execution phase, and filter/build the response.

3. The orchestrator's `execute()` method shall be no longer than 100 lines, with complex logic delegated to composed services.

4. If the reasoning phase times out, then the orchestrator shall proceed to execution phase with empty reasoning output.

5. If the reasoning phase produces tool calls without content, then the orchestrator shall short-circuit and return a tool-call-only response.

---

### Requirement 8: Injection Policy Extraction

**Objective:** As a developer, I want reasoning injection decision logic (probability, first-turn forcing, adaptive backoff) extracted into a dedicated policy engine, so that injection rules are configurable and testable independently.

**Priority:** P2 (Medium)

#### Acceptance Criteria

1. The `InjectionPolicy` service shall encapsulate all logic for deciding whether to inject reasoning for a given request.

2. When determining injection, the policy shall consider: first-turn detection, forced initial turns window, adaptive backoff state, probability override, and random sampling.

3. The policy shall return an `InjectionDecision` containing: `should_inject` (bool), `reason` (string explanation), and any updated backoff state.

4. The orchestrator shall delegate all injection decisions to the `InjectionPolicy` service.

5. If unit testing injection behavior, then the test shall be able to test the `InjectionPolicy` independently of the full orchestrator.

---

### Requirement 9: Phase Executor Extraction

**Objective:** As a developer, I want reasoning and execution phase logic extracted into a dedicated executor, so that backend interaction concerns are isolated from orchestration.

**Priority:** P1 (High)

#### Acceptance Criteria

1. The `PhaseExecutor` service shall encapsulate backend resolution, request preparation, and backend calls for both reasoning and execution phases.

2. When executing the reasoning phase, the executor shall: resolve the backend connector, apply reasoning parameters, call the backend, capture streaming output, and return a `ReasoningPhaseResult`.

3. When executing the execution phase, the executor shall: resolve the backend connector, apply execution parameters, call the backend with augmented messages, and return the response envelope.

4. If the backend is not found, then the executor shall raise a `BackendError` with appropriate context.

5. If URI parameters are provided, then the executor shall validate and apply them using the existing `URIParameterValidator`.

---

### Requirement 10: Backward Compatibility Preservation

**Objective:** As an operator, I want all existing public APIs and behaviors preserved after refactoring, so that no client code or configuration changes are required.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. The `HybridConnector` class shall remain at `src/connectors/hybrid.py` with unchanged class name and module path.

2. The `HybridConnector.__init__()` signature shall remain unchanged: `(client, config, translation_service, backend_registry)`.

3. The `HybridConnector.chat_completions()` method signature shall remain unchanged.

4. The `HybridConnector.initialize()` method shall continue to work identically.

5. The `HybridConnector.get_available_models()` method shall continue to return an empty list.

6. When existing tests are run, then 100% of tests shall pass without modification (except test file organization changes).

7. The backend registration (`backend_registry.register_backend("hybrid", HybridConnector)`) shall remain functional.

---

### Requirement 11: Test-Preserving Migration

**Objective:** As a test maintainer, I want existing test coverage preserved and enhanced during refactoring, so that code quality is maintained throughout the migration.

**Priority:** P0 (Critical)

#### Acceptance Criteria

1. When any service is extracted, the corresponding existing test cases shall continue to pass.

2. Each newly extracted service shall have dedicated unit tests in `tests/unit/connectors/hybrid_backend/`.

3. The existing integration tests in `tests/integration/connectors/test_hybrid_backend_integration.py` shall continue to pass.

4. If a test requires modification, then the modification shall only be to update import paths or fixture structure, not test logic.

5. While refactoring, the full test suite shall remain green (passing) at each checkpoint.

---

## Non-Functional Requirements

### NFR 1: Code Quality

- **Module size**: Each extracted service file shall be less than 300 lines
- **Method complexity**: No method shall exceed 15 cyclomatic complexity
- **Type safety**: All functions shall have complete type annotations
- **Documentation**: All public classes and methods shall have docstrings

### NFR 2: Performance

- **No performance regression**: The refactored code shall have equivalent or better latency compared to the current implementation
- **Memory efficiency**: No significant increase in object allocations
- **Streaming preservation**: Async generators shall remain lazy and not buffer excessively

### NFR 3: Maintainability

- **Discoverability**: New developers shall be able to find the relevant code for a concern within 2 hops from the facade
- **Testability**: Each service shall be unit-testable in isolation
- **Extensibility**: Adding a new reasoning backend type shall require changes only in infrastructure layer

### NFR 4: Observability

- **Logging preservation**: All existing log statements shall be preserved or enhanced
- **Debug traceability**: Each phase shall log its entry/exit with timing information
- **Error context**: Exceptions shall include sufficient context for debugging

---

## Glossary

| Term | Definition |
|------|------------|
| Hybrid Backend | A meta-connector that orchestrates two-phase LLM interactions (reasoning → execution) |
| Reasoning Phase | First phase where a reasoning model generates chain-of-thought output |
| Execution Phase | Second phase where an execution model produces the final response with reasoning context |
| God Object | Anti-pattern where a single class handles too many unrelated responsibilities |
| SOLID | Design principles: Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency Inversion |
| Facade Pattern | Structural pattern providing a simplified interface to a complex subsystem |
| Protocol | Python typing construct defining a structural interface (duck typing with static checking) |
| Wire Capture | CBOR-encoded traffic recording for debugging |
| Staged Init | Sequential initialization phases for services |
| DI Container | Dependency injection via `ServiceCollection` |
